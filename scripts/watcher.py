#!/usr/bin/env python3
"""
Reply Notifier for OpenClaw - WebSocket Edition
Real-time notifications via Gateway WebSocket events
Uses websocket-client library (websockets has compatibility issues)
"""

import json
import os
import sys
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime
import websocket
import http.client

# Config
GATEWAY_URL = "ws://127.0.0.1:18789"
SEEN_MESSAGES_FILE = Path(__file__).parent.parent / "logs" / "seen_messages.json"
GATEWAY_TOKEN = None

# Message tracking for deduplication
seen_messages = set()


def get_gateway_token():
    """Read token from environment or OpenClaw config."""
    # Check environment variable first (used by service)
    token = os.environ.get("OPENCLAW_GATEWAY_TOKEN")
    if token:
        return token
    
    # Try device auth
    device_auth_path = Path.home() / ".openclaw" / "identity" / "device-auth.json"
    if device_auth_path.exists():
        try:
            with open(device_auth_path) as f:
                auth = json.load(f)
            token = auth.get("tokens", {}).get("operator", {}).get("token")
            if token:
                return token
        except:
            pass
    
    # Fallback to config
    # Prefer gateway.remote.token (runtime client token), then gateway.auth.token.
    config_path = Path.home() / ".openclaw" / "openclaw.json"
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
        gateway_cfg = config.get("gateway", {})
        token = gateway_cfg.get("remote", {}).get("token") or gateway_cfg.get("auth", {}).get("token")
        if token:
            return token
    
    return None


def load_seen_messages():
    """Load previously seen message IDs."""
    global seen_messages
    if SEEN_MESSAGES_FILE.exists():
        try:
            with open(SEEN_MESSAGES_FILE) as f:
                seen_messages = set(json.load(f))
        except:
            seen_messages = set()


def save_seen_messages():
    """Save seen message IDs."""
    SEEN_MESSAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SEEN_MESSAGES_FILE, 'w') as f:
        json.dump(list(seen_messages), f)


def play_notification_sound(sound="Glass"):
    """Play macOS notification sound - synchronous to ensure it plays."""
    sound_path = f"/System/Library/Sounds/{sound}.aiff"
    if os.path.exists(sound_path):
        try:
            subprocess.run(["afplay", sound_path], check=False, timeout=5)
        except:
            pass


def log(message):
    """Print with timestamp."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")


def on_open(ws):
    """Called when WebSocket connection opens."""
    log("Connected to Gateway")
    
    # Send connect handshake with correct format
    import uuid
    
    connect_msg = {
        "type": "req",
        "id": str(uuid.uuid4()),
        "method": "connect",
        "params": {
            "minProtocol": 3,
            "maxProtocol": 3,
            "client": {
                "id": "cli",
                "version": "1.0.0",
                "platform": "macos",
                "mode": "cli"
            },
            "role": "operator",
            "scopes": ["operator.read"]
        }
    }
    
    # Add auth if token exists
    if GATEWAY_TOKEN:
        connect_msg["params"]["auth"] = {"token": GATEWAY_TOKEN}
    
    ws.send(json.dumps(connect_msg))
    log("Sent connect handshake")


def on_message(ws, message):
    """Called when message received."""
    try:
        data = json.loads(message)
        
        # Log response messages for debugging
        if data.get("type") == "res":
            if data.get("ok"):
                log("Authentication successful")
                log("Listening for agent events...")
                log("Press Ctrl+C to stop\n")
            else:
                log(f"Connection failed: {data.get('error', 'unknown error')}")
                return
        else:
            handle_event(data)
    except json.JSONDecodeError:
        pass


def on_error(ws, error):
    """Called on error."""
    log(f"WebSocket error: {error}")


def on_close(ws, close_status_code, close_msg):
    """Called when connection closes."""
    log(f"Connection closed (code: {close_status_code})")


def handle_event(event):
    """Handle incoming Gateway events."""
    if event.get("type") != "event":
        return
    
    event_type = event.get("event")
    payload = event.get("payload", {})
    
    # Listen for agent lifecycle events
    if event_type == "agent":
        handle_agent_event(payload)


# Track run start times for duration calculation
run_start_times = {}

def handle_agent_event(payload):
    """Handle agent events - detect when runs complete."""
    global run_start_times
    
    stream = payload.get("stream")
    data = payload.get("data", {})
    run_id = payload.get("runId", "unknown")
    
    # Only care about lifecycle events
    if stream != "lifecycle":
        return
    
    phase = data.get("phase")
    
    if phase == "start":
        run_start_times[run_id] = time.time()
        log(f"Run started: {run_id[:8]}...")
        
    elif phase == "end":
        start_time = run_start_times.pop(run_id, None)
        duration = time.time() - start_time if start_time else 0
        log(f"Run completed: {run_id[:8]}... ({duration:.1f}s)")
        # Small delay to ensure message is in history
        time.sleep(0.5)
        check_for_new_replies(duration)
        
    elif phase == "error":
        run_start_times.pop(run_id, None)
        error_msg = data.get("error", "unknown error")
        log(f"Run error: {run_id[:8]}... - {error_msg}")


def check_for_new_replies(run_duration=0):
    """Check sessions for new assistant replies."""
    try:
        # Get sessions list
        conn = http.client.HTTPConnection("127.0.0.1", 18789, timeout=5)
        
        # sessions_list
        payload = json.dumps({
            "tool": "sessions_list",
            "args": {"limit": 10},
            "sessionKey": "main"
        })
        
        headers = {
            "Content-Type": "application/json"
        }
        
        if GATEWAY_TOKEN:
            headers["Authorization"] = f"Bearer {GATEWAY_TOKEN}"
        
        conn.request("POST", "/tools/invoke", body=payload, headers=headers)
        resp = conn.getresponse()
        
        if resp.status != 200:
            conn.close()
            return
        
        data = json.loads(resp.read().decode())
        conn.close()
        
        if not data.get("ok"):
            return
        
        result = data.get("result", {})
        content = result.get("content", [])
        
        if not content or not isinstance(content[0], dict):
            return
        
        try:
            sessions_data = json.loads(content[0].get("text", "{}"))
        except json.JSONDecodeError:
            return
        
        sessions = sessions_data.get("sessions", [])
        
        new_replies = []
        
        for session in sessions:
            session_key = session.get("key") or session.get("sessionKey")
            if not session_key:
                continue
            
            # Get recent messages
            conn = http.client.HTTPConnection("127.0.0.1", 18789, timeout=5)
            
            payload = json.dumps({
                "tool": "sessions_history",
                "args": {"sessionKey": session_key, "limit": 3},
                "sessionKey": session_key
            })
            
            conn.request("POST", "/tools/invoke", body=payload, headers=headers)
            resp = conn.getresponse()
            
            if resp.status != 200:
                conn.close()
                continue
            
            data = json.loads(resp.read().decode())
            conn.close()
            
            if not data.get("ok"):
                continue
            
            result = data.get("result", {})
            content = result.get("content", [])
            
            if not content or not isinstance(content[0], dict):
                continue
            
            try:
                history = json.loads(content[0].get("text", "{}"))
            except json.JSONDecodeError:
                continue
            
            messages = history.get("messages", [])
            
            for msg in messages:
                msg_id = str(msg.get("timestamp", ""))
                stop_reason = msg.get("stopReason")
                role = msg.get("role", "")
                
                if not msg_id or msg_id in seen_messages:
                    continue
                
                # Mark as seen immediately
                seen_messages.add(msg_id)
                
                # Check if it's a completed assistant message
                if role == "assistant" and stop_reason in ["stop", "end_turn", "length"]:
                    # Get message text
                    content_parts = msg.get("content", [])
                    text_parts = []
                    for part in content_parts:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                    
                    full_text = " ".join(text_parts).strip()
                    
                    # ALWAYS notify for every reply, regardless of length
                    preview = full_text[:60] + "..." if len(full_text) > 60 else full_text
                    new_replies.append((session_key, preview, run_duration))
        
        # Notify for new replies
        if new_replies:
            for session_key, preview, duration in new_replies:
                duration_str = f" ({duration:.1f}s)" if duration > 0 else ""
                log(f"🔔 New reply{duration_str}: {preview}")
                play_notification_sound()
            
            save_seen_messages()
            
    except Exception as e:
        log(f"Error checking replies: {e}")


def run_websocket_client():
    """Main WebSocket client loop with reconnection."""
    global GATEWAY_TOKEN
    
    GATEWAY_TOKEN = get_gateway_token()
    
    if GATEWAY_TOKEN:
        log("Gateway token loaded")
    else:
        log("No gateway token found")
        log("Set OPENCLAW_GATEWAY_TOKEN or configure gateway.remote.token in ~/.openclaw/openclaw.json")
    
    load_seen_messages()
    log(f"Loaded {len(seen_messages)} seen message IDs")
    
    while True:
        try:
            log(f"Connecting to {GATEWAY_URL}...")
            
            # Create WebSocket connection
            ws = websocket.WebSocketApp(
                GATEWAY_URL,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            
            # Run forever (blocks until connection closes)
            ws.run_forever()
            
            # If we get here, connection closed - reconnect after delay
            log("Reconnecting in 3 seconds...")
            time.sleep(3)
            
        except KeyboardInterrupt:
            log("\nShutting down...")
            save_seen_messages()
            log(f"Saved {len(seen_messages)} seen message IDs")
            break
        except Exception as e:
            log(f"Error: {e}")
            time.sleep(3)


def main():
    """Main entry point."""
    print("=" * 50)
    print("Reply Notifier (WebSocket Edition) starting...")
    print("=" * 50)
    
    try:
        run_websocket_client()
    except KeyboardInterrupt:
        log("\nShut down by user")
        save_seen_messages()


if __name__ == "__main__":
    main()
