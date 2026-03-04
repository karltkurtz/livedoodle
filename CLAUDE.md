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
| `GET /` | Home page — branding, live snapshot feed, DRAW! button |
| `GET /draw` | Mobile drawing canvas |
| `GET /display` | Pi A kiosk display (zero UI) |
| `GET /snapshot` | Latest JPEG frame from camera Pi (polled every 100ms) |
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

### Planned: Additional WS Message Types

```json
// Draw → server (submit artwork; server saves to artwork_history.json)
{"type": "finish", "name": "Karl"}

// Draw → server (same as clear but also triggers artwork save before clearing)
{"type": "clear"}
```

On `finish` or `clear`, the server calls `end_session(websocket, name)` which:
1. Snapshots current `history` for that connection
2. Looks up geo from `_geo_cache` using the connection's IP
3. Appends entry to `artwork_history.json` (max 50, drop oldest)
4. Clears history and broadcasts clear to display clients

## Files

```
main.py                  # FastAPI app, ConnectionManager, all routes + WS endpoint
templates/home.html      # Public home page (branding, snapshot feed, DRAW! button)
templates/draw.html      # Self-contained drawing page (canvas, toolbar, WS client)
templates/display.html   # Self-contained kiosk page (canvas, WS client, no UI)
templates/artwork.html   # [planned] Gallery page — fetches /artwork/entries, replays strokes on canvases
artwork_history.json     # [planned] Flat JSON array of saved artwork entries (max 50)
requirements.txt         # fastapi, uvicorn[standard], jinja2, python-multipart
livedoodle.service       # systemd unit for Pi A (/home/karltkurtz/livedoodle, port 8000)
website-aesthetic.rtf    # Design brief — retro arcade / lo-fi pixel art aesthetic
```

## Visual Design

**Aesthetic:** Retro arcade / lo-fi pixel art — 1980s computer terminal crossed with a neon-lit arcade cabinet. See `website-aesthetic.rtf` for the full brief.

**Rules:**
- Font: `Share Tech Mono` (monospace) throughout all UI — no decorative or sans-serif fonts
- Background: `#0a0a0a` (near-black)
- Accent palette (amber, teal, coral, green, purple) — all saturated, used with `box-shadow` neon glows
- Buttons: dark fill + vivid colored border + glow; no rounded pills, no gradients
- Labels: ALL-CAPS, terse
- Animations: pixel starfield (small squares drifting upward) on home page; cycling color animation (10s loop: amber → teal → coral → green → purple) on primary CTA; blinking dot on LIVE badge
- Scanline overlay on home page via `repeating-linear-gradient`
- No shadows for depth, no gradients for realism — flat + glowing only

**Per-page notes:**
- `home.html`: starfield canvas in background, DRAW! button cycles through accent colors, corner-bracket frame around stream feed; dim stats row after actions showing visitor count + recent cities
- `draw.html`: toolbar only (canvas stays white as drawing surface), amber top-border glow on toolbar, square swatches with glow on active, teal glow for ERASER active, coral glow for CLEAR hover; DONE button triggers name prompt then sends `{type:"finish", name}`
- `artwork.html`: [planned] grid of past artwork canvases; each replays its stroke list; shows name, location, date

## Hardware Context

- **Pi A (server Pi):** Raspberry Pi 4, hostname `litebrite`, username `karltkurtz`. Runs the FastAPI server, 7" display attached. `/display` runs in Chromium kiosk mode fullscreen.
- **Pi B (camera Pi):** Raspberry Pi 4 with HQ camera pointed at Pi A's display. Already streams — no code changes needed.
- Both on Ethernet LAN. Exposed publicly via Cloudflare tunnel at `pigarage.com` → port 8000.
- Server binds to `0.0.0.0` and uses `--proxy-headers` to respect `X-Forwarded-For` from Cloudflare.

## Deploy Flow

**Workflow:** Make code changes → open Safari to preview → user says "commit" → commit + push + deploy.

- NEVER auto-commit. Only commit when user explicitly says "commit".
- After making changes, always open Safari to the relevant pigarage.com page for review.
- After user approves (says "commit"), do all three steps automatically: commit, push, deploy.

```bash
# 1. Commit and push from Mac
git add <specific files> && git commit -m "message"
git push

# 2. Deploy to Pi A (use IP — hostname 'litebrite' doesn't resolve from Mac)
ssh karltkurtz@10.0.0.81 "cd ~/livedoodle && git pull && sudo systemctl restart livedoodle"
# If Pi has local changes, stash first:
ssh karltkurtz@10.0.0.81 "cd ~/livedoodle && git stash && git pull && sudo systemctl restart livedoodle"
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

## Known Issues

### Stamp not appearing on Pi display
Stamp feature works on draw page (mobile) — image is placed on the draw canvas correctly. But the stamp does not appear on the Pi display (`/display`). Likely causes:
- WebSocket message is too large and silently dropped (Cloudflare WebSocket frame limit, or Starlette `receive_text` default max size)
- Silent WS send failure: `send()` in draw.html drops the message if `ws.readyState !== OPEN`, with no retry
- Investigate by logging received message types in display.html or checking server-side relay

## Planned Features

### 1. Visitor Count + Geolocation
Add to `main.py`:
- `_get_client_ip(request)` — reads `CF-Connecting-IP` → `X-Forwarded-For` → `request.client.host`
- `_lookup_geo(ip)` — `GET http://ip-api.com/json/{ip}?fields=city,regionName,country`, 3s timeout, fallback `""`, cached in `_geo_cache: dict[str, str]`
- `_unique_ips: set[str]` — unique visitor count
- `_recent_locations: list[str]` — newest first, capped at 20; format "City, Region, Country"
- Skip geo for private/loopback IPs
- Pass `visitor_count` and `recent_locations` to `home.html`

Display in `home.html`: dim stats row after `#actions` — `"NNN VISITORS // CITY • CITY • CITY"`. Font 8px, green count at low opacity, very dark location text.

### 2. Past Artwork Gallery
Add to `main.py`:
- `end_session(websocket, name)` — snapshots history, looks up geo from cache by connection IP, appends to `artwork_history.json` (max 50 entries, drop oldest), clears board
- Handle `{type: "finish", name}` WS message from draw clients → call `end_session()`
- Handle `{type: "clear"}` → also call `end_session()` before clearing (save anonymous if strokes exist)
- `GET /artwork/entries` — returns `artwork_history.json` as JSON
- `GET /artwork` — serves `artwork.html`

Entry format:
```json
{"strokes": [...], "name": "Karl", "location": "Austin, Texas, US", "time": 1709123456.789, "duration": 183}
```

Add to `draw.html`:
- DONE button → name prompt popup → sends `{type: "finish", name}` over WS
- Track session start time client-side for `duration`

Add `templates/artwork.html`: fetches `/artwork/entries`, renders each as a canvas by replaying strokes. Shows name, location, date. Same retro aesthetic.

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
@bash -c 'sleep 5 && chromium --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble http://localhost:8000/display'
```

The `sleep 5` is required — without it, Chromium launches before the FastAPI server is ready and silently fails. If Chromium is ever not showing on the Pi display, launch it manually:

```bash
ssh karltkurtz@10.0.0.81 "DISPLAY=:0 chromium --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble http://localhost:8000/display &"
```

