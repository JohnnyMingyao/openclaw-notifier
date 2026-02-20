# Reply Notifier Plugin (WebSocket Edition)

Real-time notifications for OpenClaw replies via Gateway WebSocket events.

## How It Works

```
┌─────────────┐     WebSocket      ┌──────────────┐     detects      ┌─────────────────┐
│ OpenClaw GW │ ◀───────────────── │ Watcher      │ ───────────────▶ │ macOS sound     │
│ :18789      │  real-time events  │ (this plugin)│   agent end      │ ("Glass")       │
└─────────────┘                    └──────────────┘                  └─────────────────┘
```

**Old way**: Poll every 3 seconds (wasteful, delayed)
**New way**: WebSocket connection receives instant `agent` lifecycle events

## What's New (WebSocket Edition)

- **Instant**: No polling delay — sound plays immediately when run completes
- **Efficient**: One persistent connection instead of 20+ API calls per minute
- **Event-driven**: Listens for Gateway `agent` events with `lifecycle` phase `end` or `error`
- **Same deduplication**: Still tracks seen messages via timestamp

## Requirements

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install websocket-client
```

## Quick Start

### 1. Configure token (required)

```bash
cd ${HOME}/Documents/Projects/reply-notifier
cp .env.example .env
# edit .env and fill OPENCLAW_GATEWAY_TOKEN
export OPENCLAW_GATEWAY_TOKEN="<your gateway.remote.token>"
```

### 2. Test the Watcher

```bash
cd ${HOME}/Documents/Projects/reply-notifier
source .venv/bin/activate
python3 scripts/watcher.py
```

You should see:
```
==================================================
Reply Notifier (WebSocket Edition) starting...
==================================================
[20:05:32] Gateway token loaded
[20:05:32] Loaded 42 seen message IDs
[20:05:32] Connecting to ws://127.0.0.1:18789...
[20:05:32] Connected to Gateway
[20:05:32] Authenticated successfully
[20:05:32] Listening for agent events...
[20:05:32] Press Ctrl+C to stop
```

When I reply, you'll see:
```
[20:06:15] Run started: a1b2c3d4...
[20:06:18] Run completed: a1b2c3d4...
[20:06:18] New reply in main: Hey Monoko, what's up?
[20:06:18] 🔊 Glass sound plays
```

### 3. Enable Auto-Start

Before loading LaunchAgent, replace placeholders in `config/com.monoko.reply-notifier.plist`:
- `__REPLY_NOTIFIER_ROOT__` → your local path (e.g. `${HOME}/Documents/Projects/reply-notifier`)
- `__OPENCLAW_GATEWAY_TOKEN__` → your `gateway.remote.token`

```bash
# Copy LaunchAgent to system location
cp config/com.monoko.reply-notifier.plist ~/Library/LaunchAgents/

# Load and start
launchctl load ~/Library/LaunchAgents/com.monoko.reply-notifier.plist
launchctl start com.monoko.reply-notifier
```

Check status:
```bash
launchctl list | grep reply-notifier
```

View logs:
```bash
tail -f <REPLY_NOTIFIER_ROOT>/logs/output.log
```

To disable:
```bash
launchctl unload ~/Library/LaunchAgents/com.monoko.reply-notifier.plist
```

## Configuration

Edit `scripts/watcher.py` to customize:

| Variable | Default | Description |
|----------|---------|-------------|
| `GATEWAY_URL` | `ws://127.0.0.1:18789` | WebSocket endpoint |
| Sound | `"Glass"` | macOS sound name (see list below) |

### Available Sounds

Basso, Blow, Bottle, Frog, Funk, **Glass** (default), Hero, Morse, Ping, Pop, Purr, Sosumi, Submarine, Tink

Change sound (edit line 75 in `watcher.py`):
```python
play_notification_sound("Hero")  # Instead of "Glass"
```

## How It Detects Replies

1. **Connects** to Gateway WebSocket
2. **Authenticates** with Bearer token
3. **Listens** for `agent` events
4. On `lifecycle` phase `end` or `error`:
   - Brief delay (0.5s) to let message appear in history
   - Queries `sessions_history` for recent messages
   - Finds new assistant messages with `stopReason` indicating completion
   - Plays sound for substantial replies (>10 chars)

## Troubleshooting

**"ModuleNotFoundError: No module named 'websocket'"**
```bash
source .venv/bin/activate
pip install websocket-client
```

**"Could not read gateway token"**
- Ensure OpenClaw is running: `openclaw gateway status`
- Check config exists: `cat ~/.openclaw/openclaw.json | grep token`

**"Connection closed" appearing repeatedly**
- Gateway may be restarting — the watcher auto-reconnects
- Check Gateway is running: `openclaw gateway status`

**No sound playing**
- Check sound file exists: `ls /System/Library/Sounds/Glass.aiff`
- Test manually: `afplay /System/Library/Sounds/Glass.aiff`
- Check Notification permissions in System Settings

**Missing replies**
- Check logs: `tail -f logs/output.log`
- Ensure watcher is connected (should show "Listening for agent events...")
- Messages might be too short (<10 chars) — adjust threshold in code if needed

## Architecture

### Event Flow

```
┌──────────────┐    connect     ┌─────────────┐
│ Your Mac     │ ─────────────▶ │ Gateway     │
│ (watcher.py) │                │ (18789)     │
└──────────────┘                └─────────────┘
       │                               │
       │  ◀──── agent lifecycle ----   │
       │       {phase: "start"}        │
       │                               │
       │  ◀---- agent lifecycle ----   │
       │       {phase: "end"}          │
       │                               │
       ▼                               ▼
  [Query history]               [LLM generates]
       │                               │
       ▼                               ▼
  [New assistant msg]           [Message saved]
       │                               │
       ▼                               ▼
  [Play Glass sound]            [Event emitted]
```

### Why WebSocket?

| Metric | Old (Polling) | New (WebSocket) |
|--------|---------------|-----------------|
| Latency | 0-3 seconds | Instant |
| API calls/min | ~20 | ~2-3 (only after events) |
| CPU usage | Constant | Near-zero when idle |
| Battery | Drains faster | Efficient |

## Files

```
reply-notifier/
├── .env.example                # Fill token placeholder
├── scripts/
│   └── watcher.py              # Main WebSocket daemon
├── config/
│   └── com.monoko.reply-notifier.plist  # Replace placeholders before load
├── logs/
│   ├── output.log              # Runtime output
│   ├── error.log               # Errors
│   └── seen_messages.json      # Tracks already-notified messages
└── README.md                   # This file
```

## Upgrade Notes

If you had the old polling version:
- The `seen_messages.json` format is compatible
- Just replace `watcher.py` with the new WebSocket version
- Install dependency if missing: `pip install websocket-client`

---

Part of the OpenClaw extensions ecosystem.
