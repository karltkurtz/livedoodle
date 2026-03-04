# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run dev server (with hot reload)
uvicorn main:app --reload

# Run production-style (matches Pi A service)
uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers

# Install dependencies
pip install -r requirements.txt
```

No build step. No Node. No npm.

## Architecture

Single-file FastAPI server (`main.py`) with two HTML templates.

### Routes

| Route | Description |
|-------|-------------|
| `GET /` | Redirects to `/draw` |
| `GET /draw` | Mobile drawing canvas |
| `GET /display` | Pi A kiosk display (zero UI) |
| `WS /ws?role=draw\|display` | Single WebSocket endpoint |

### WebSocket Protocol

Clients connect to `/ws` with a `role` query param. The server's `ConnectionManager` class tracks two sets:
- **draw clients** — send stroke/clear commands; server relays to display clients
- **display clients** — receive relayed strokes; receive full history sync on connect

**Message types:**

```json
// Draw → server → display clients
{"type": "stroke", "color": "#ff0000", "size": 6, "x0": 0.1, "y0": 0.2, "x1": 0.15, "y1": 0.25}

// Draw → server → display clients (server clears history)
{"type": "clear"}

// Server → new display client only (history replay)
{"type": "sync", "history": [...stroke objects...]}
```

### Coordinates

Strokes use **normalized coordinates** (0.0–1.0). The drawing client divides by its canvas dimensions before sending; the display client multiplies by its canvas dimensions when rendering. This makes phone canvas size and Pi display size irrelevant.

### State

`ConnectionManager.history` holds all strokes since the last clear. It's unbounded but resets on clear. New display clients receive the full history as a single `sync` message and replay it immediately.

## Files

```
main.py                  # FastAPI app, ConnectionManager, all routes + WS endpoint
templates/draw.html      # Self-contained drawing page (canvas, toolbar, WS client)
templates/display.html   # Self-contained kiosk page (canvas, WS client, no UI)
requirements.txt         # fastapi, uvicorn[standard], jinja2, python-multipart
livedoodle.service       # systemd unit for Pi A (/home/karltkurtz/livedoodle, port 8000)
```

## Hardware Context

- **Pi A (server Pi):** Raspberry Pi 4, hostname `litebrite`, username `karltkurtz`. Runs the FastAPI server, 7" display attached. `/display` runs in Chromium kiosk mode fullscreen.
- **Pi B (camera Pi):** Raspberry Pi 4 with HQ camera pointed at Pi A's display. Already streams — no code changes needed.
- Both on Ethernet LAN. Exposed publicly via Cloudflare tunnel at `pigarage.com` → port 8000.
- Server binds to `0.0.0.0` and uses `--proxy-headers` to respect `X-Forwarded-For` from Cloudflare.

## Deploy Flow

```bash
# 1. Commit and push from Mac
git add -A && git commit -m "message"
git push

# 2. On Pi A
ssh karltkurtz@litebrite
cd ~/livedoodle && git pull
sudo systemctl restart livedoodle
```

## Pi A Service

The systemd service is at `livedoodle.service`. It is already installed and enabled on Pi A.

```bash
# Re-install after changes to the service file
sudo cp livedoodle.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable livedoodle
sudo systemctl start livedoodle
```

Logs: `sudo journalctl -u livedoodle -f`

## Pi A Chromium Kiosk

Autostart config lives at the **user level** (system-level path does not exist on this Pi OS version):

```
~/.config/lxsession/LXDE-pi/autostart
```

Contents:
```
@xset s off
@xset -dpms
@xset s noblank
@chromium --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble http://localhost:8000/display
```

