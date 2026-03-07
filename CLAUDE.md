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

Single-file FastAPI server (`main.py`) with Jinja2 templates.

### Routes

| Route | Description |
|-------|-------------|
| `GET /` | Home page — branding, live snapshot feed, DRAW! button, presence status |
| `GET /draw` | Mobile drawing canvas |
| `GET /display` | Pi A kiosk display (zero UI) |
| `GET /about` | About page — what it is, how it works, hardware setup |
| `GET /donate` | Donate page — build story, BOM, Venmo button (placeholder) |
| `GET /artwork` | Past artwork gallery; `?edit=1` activates admin edit mode |
| `GET /artwork/entries` | JSON array of saved artwork entries |
| `POST /artwork/delete` | Delete a single artwork entry by timestamp (password-protected) |
| `POST /artwork/edit-start` | Set `_artwork_editing = True` (password-protected) |
| `POST /artwork/edit-end` | Set `_artwork_editing = False` (password-protected) |
| `GET /guestbook` | Guestbook page with sign form |
| `GET /guestbook/entries` | JSON array of guestbook entries |
| `POST /guestbook/sign` | Submit a guestbook entry |
| `GET /admin` | Password-protected admin page |
| `POST /admin/auth` | Verify admin password |
| `POST /admin/clear-guestbook` | Clear all guestbook entries |
| `POST /admin/clear-artwork` | Clear all artwork entries |
| `POST /admin/set-home` | Set presence to "I AM HOME" |
| `POST /admin/set-away` | Set presence to "I AM AWAY" |
| `POST /admin/reload-display` | Broadcast `{type:"reload"}` to all display clients |
| `GET /snapshot` | Latest JPEG frame from camera Pi (polled every 100ms) |
| `GET /status` | JSON: `{drawing, session_elapsed, viewers, last_location, artwork_editing}` — polled every 500ms by home page |
| `GET /activity` | JSON: `{last_visitor_time}` — polled every 5s by display page for screensaver |
| `WS /ws?role=draw\|display\|view` | Single WebSocket endpoint |

### WebSocket Protocol

Clients connect to `/ws` with a `role` query param. The server's `ConnectionManager` class tracks two sets:
- **draw clients** — send stroke/stamp/finish/clear/wipe/redraw commands; server relays to display clients
- **display clients** — receive relayed strokes; receive full history sync on connect

**Message types:**

```json
// Draw → server → display clients
{"type": "stroke", "color": "#ff0000", "size": 0.015, "x0": 0.1, "y0": 0.2, "x1": 0.15, "y1": 0.25}

// Draw → server → display clients
{"type": "stamp", "data": "<dataURL>", "x": 0.5, "y": 0.5, "w": 0.4, "h": 0.24}

// Draw → server → display clients (flood fill; coords normalized)
{"type": "fill", "x": 0.3, "y": 0.5, "color": "#ff0000"}

// Draw → server (keep screensaver away while page is open)
{"type": "heartbeat"}

// Draw → server (save artwork, don't clear board)
{"type": "finish", "name": "Karl", "duration": 183}

// Draw → server (save artwork + clear board) — NOT used by CLEAR button; only for future use
{"type": "clear", "name": "Karl", "duration": 183}

// Draw → server (clear board only, no artwork saved) — sent by CLEAR button
{"type": "wipe"}

// Draw → server (replace history, resync displays)
{"type": "redraw", "history": [...]}

// Server → new display/draw client (history replay)
{"type": "sync", "history": [...stroke/stamp/fill objects...]}

// Server → display clients (clear canvas)
{"type": "clear"}

// Server → display clients (force page reload)
{"type": "reload"}
```

### Coordinates and Sizing

All stroke coordinates and stamp positions/sizes use **normalized values** (0.0–1.0) relative to canvas dimensions.

**Stroke size** is also normalized: stored as `brushSize / canvas.width`. When rendering, multiply by the target canvas width. This ensures consistent visual thickness across phone, Pi display, and artwork cards.

**Backward compatibility:** Old strokes (before normalization) have `size >= 1` (absolute pixels). New strokes have `size < 1` (normalized). Renderers check `s.size >= 1 ? s.size : s.size * canvasWidth`.

### State

`ConnectionManager.history` holds all strokes/stamps/fills since the last clear. Resets on clear. New clients receive the full history as a single `sync` message.

`_last_visitor_time: float` — updated whenever a draw client connects, sends a heartbeat or stroke, or the home page polls `/status`. Used by `/display` to decide when to show the screensaver.

`_artwork_editing: bool` — set `True` by `POST /artwork/edit-start`, `False` by `POST /artwork/edit-end`. Included in `/status` so the home page PAST ARTWORK button disables cross-device when the admin is in edit mode.

## Files

```
main.py                    # FastAPI app, ConnectionManager, all routes + WS endpoint
templates/home.html        # Public home page
templates/draw.html        # Mobile drawing page (canvas, toolbar, WS client)
templates/display.html     # Pi kiosk page (canvas, WS client, no UI)
templates/artwork.html     # Past artwork gallery (with lightbox on click)
templates/guestbook.html   # Guestbook with sign form
templates/about.html       # About page
templates/donate.html      # Donate page (Venmo placeholder — needs real username)
templates/admin.html       # Password-protected admin panel
artwork_history.json       # Flat JSON array of saved artwork entries (max 25)
guestbook.json             # Flat JSON array of guestbook entries (max 200)
home_status.json           # Persisted presence status: {"home": true|false}
og-image.png               # Open Graph image served at /og-image.png (639×507)
requirements.txt           # fastapi, uvicorn[standard], jinja2, python-multipart, httpx
livedoodle.service         # systemd unit for Pi A (/home/karltkurtz/livedoodle, port 8000)
website-aesthetic.rtf      # Design brief — retro arcade / lo-fi pixel art aesthetic
```

## Visual Design

**Aesthetic:** Retro arcade / lo-fi pixel art — 1980s computer terminal crossed with a neon-lit arcade cabinet.

**Rules:**
- Font: `Share Tech Mono` (monospace) throughout — no other fonts
- Background: `#0a0a0a` (near-black)
- All body/label/meta text: `#555` — this is the standard gray across all pages
- Accent palette: `--amber: #ffb300`, `--teal: #00e5ff`, `--coral: #ff4a2a`, `--green: #39ff14`, `--purple: #bf5fff`
- Buttons: dark fill + vivid colored border + `box-shadow` glow; no rounded corners, no gradients
- Labels: ALL-CAPS, terse, `letter-spacing: 0.2em+`
- Pixel starfield on every page: 40 × 3px squares drifting upward, drawn on a fixed `<canvas id="starfield">`
- Scanline overlay via `body::before` `repeating-linear-gradient` on all pages
- `#page` is always `position: relative; z-index: 1` to sit above the starfield
- No shadows for depth, no gradients for realism — flat + glowing only

**Per-page accent colors:**
- `home.html`: amber h1, teal rule/wordmark, cycling DRAW! button
- `draw.html`: amber toolbar border
- `artwork.html`: green h1 + rule
- `guestbook.html`: purple h1 + rule
- `donate.html`: coral h1 + rule
- `about.html`: teal h1 + rule
- `admin.html`: amber h1 + rule

**Home page specifics:**
- Blinking coral dot before "LIVEDOODLE" wordmark (`#wordmark-dot`)
- LIVE badge overlaid top-right of livestream (`position: absolute` inside `#stream-inner`)
- Both blink dots synced via JS `animationDelay` at page load
- Presence status (`#presence`) in meta row: "I AM HOME" (green) or "I AM AWAY" (amber) — rendered server-side via Jinja2
- h1: `clamp(35px, 9.4vw, 59px)` — reduced ~33% from original
- DRAW! button amber when busy (someone else drawing), shows countdown timer
- Corner-bracket frame around livestream via `::before`/`::after` pseudo-elements on `#stream-frame` and `#stream-inner`

**Draw page specifics:**
- Timer bar below canvas, 36px coral countdown
- Slider rail white, amber square thumb
- Stamp buttons: REMOVE (coral) and KEEP (green) — appear as a fixed-size amber-bordered popup centered in the toolbar; toolbar dims to 5% opacity when stamp mode is active; uses `visibility` (not `display`) so toolbar height never shifts and canvas never clips
- FILL button present in toolbar but currently disabled — shows amber toast "THE FILL BUTTON IS BEING WORKED ON." for 3s on tap; fill infrastructure is fully wired (see Fill section below)
- SHAPES, EMOJI, QUOTES pickers open as full-screen overlay modals (dark backdrop, centered panel); BRUSH expands inline
- Picker toggle buttons: SHAPES=purple (72px), BRUSH=teal (72px), EMOJI=amber (72px), QUOTES=coral (72px)
- All `#btn-row` buttons are permanently lit accent colors (never greyed out); have a CSS tap animation (`@keyframes btn-tap`) on `pointerdown`
- Daily drawing prompt shown between timer bar and canvas: "DAILY DRAWING CHALLENGE: [prompt]" — rotates daily via `date.toordinal() % len(PROMPTS)` in `main.py`

## Admin Page

- URL: `/admin`
- Password: stored server-side as `ADMIN_PASSWORD` in `main.py` — never in templates
- JS stores password in memory after unlock; sends with each POST request
- Sections: Camera preview (live, 1fps), Presence toggle, Camera controls, Clear Guestbook, Clear Artwork
- Camera controls: brightness, contrast, saturation, exposure (μs), gain — 120ms debounced; proxied via `POST /admin/camera-control` → Pi B's `/controls` endpoint
- AUTO RESET button sends `{"auto": true}` to re-enable auto-exposure on Pi B (AE is disabled when any manual control is set)
- **EDIT button** (Past Artwork section): stores password in `sessionStorage("adminPw")` and navigates to `/artwork?edit=1`

## Artwork Edit Mode

Accessed via `/artwork?edit=1` (only from admin EDIT button).

- Each artwork card shows a red × button; clicking it calls `POST /artwork/delete` (by `time` timestamp) and removes the card from DOM
- Green DONE EDITING bar at top; clicking it clears sessionStorage and navigates back to `/artwork`
- **HOME nav link** on `/artwork` is disabled (opacity 0.3, pointer-events none) while in edit mode
- **PAST ARTWORK button** on `/home` shows "PLEASE WAIT..." and is non-clickable while edit mode is active — driven by `_artwork_editing` server flag via the `/status` poll, so it works cross-device (mobile visitors see it too)
- On edit mode enter: `POST /artwork/edit-start` sets server flag
- On DONE EDITING: `POST /artwork/edit-end` clears server flag
- On accidental exit (tab close, navigation): `navigator.sendBeacon` to `POST /artwork/edit-end` fires during page unload

## Screensaver (`/display`)

- Activates after `IDLE_TIMEOUT_S = 20` seconds of no visitor activity
- Idle is detected by polling `GET /activity` every 5s and checking `last_visitor_time`
- `_last_visitor_time` is updated by: draw WS connect, heartbeat messages, strokes, and `/status` HTTP polls (home page)
- Screensaver: dark overlay with amber "LIVEDOODLE" title + teal subtitle, blinking coral dot, pixel starfield, slow Lissajous drift on content to prevent burn-in
- Drift bounds computed from `ssContent.offsetWidth/Height` — content never leaves viewport
- Cursor hidden by default (`cursor: none`); shown for 10s on mousemove/touchstart via `body.cursor-visible` class

## Fill Tool (Infrastructure Complete, UI Disabled)

The fill (flood fill / bucket) pipeline is fully implemented end-to-end but the button is disabled with a toast while LCD rendering is investigated.

**Protocol:** `{type: "fill", x: <normalized>, y: <normalized>, color: "#rrggbb"}`

**Where fill is handled:**
- `draw.html`: `floodFill()` function; `startDraw()` triggers it when `isFilling`; `flatHistory()` includes fills from undoStack; `replayHistory()` handles fill type
- `display.html`: `floodFill()` function; `redraw()` and `handleMessage()` handle fill type
- `artwork.html`: `replayOnCanvas()` has inline `doFill()` for gallery replay
- `main.py`: `update_history()` accepts fill; WS relay whitelist includes fill; redraw history filter includes fill

**Known issue:** Fill works on draw.html (user sees it) and saves to artwork correctly, but does NOT render on the Pi LCD display. Two fixes already attempted with no success:
1. Added `{ willReadFrequently: true }` to `canvas.getContext("2d")` in display.html
2. Replaced `ctx.clearRect` with explicit `ctx.fillStyle="#ffffff"; ctx.fillRect(...)` so getImageData reads opaque pixels instead of transparent

Next things to try:
- SSH to Pi and open browser dev tools to check for JS errors during fill
- Test if `ctx.getImageData` returns correct data on Pi by logging pixel values
- Try wrapping `floodFill` call in `requestAnimationFrame` in display.html to flush GPU before pixel read
- Check if Pi's Chromium version has known `getImageData` bugs on hardware-accelerated canvases
- Consider sending fill result as a full canvas snapshot (dataURL stamp) instead of re-computing flood fill on display

## Presence / Home Status

- Stored in `home_status.json`, loaded on startup into `_is_home: bool`
- Passed to `home.html` as Jinja2 template variable `is_home`
- Toggle via `POST /admin/set-home` or `POST /admin/set-away` (password required)
- Old unauthenticated `POST /set-home` and `POST /set-away` endpoints still exist — consider removing

## Hardware Context

- **Pi A (server Pi):** Raspberry Pi 4, hostname `litebrite`, IP `10.0.0.81`, username `karltkurtz`. Runs FastAPI, 7" display. `/display` in Chromium kiosk mode.
- **Pi B (camera Pi):** Raspberry Pi 4 with HQ camera at `http://10.0.0.8:8080/?action=snapshot`. Runs `stream.py` with picamera2. Has a `/controls` POST endpoint accepting JSON with lowercase keys: `brightness`, `contrast`, `saturation`, `exposure`, `gain`, `auto`. Sending `{"auto": true}` recreates the camera to re-enable auto-exposure.
- Cloudflare tunnel → `pigarage.com` → port 8000.
- Server uses `--proxy-headers` for `CF-Connecting-IP` / `X-Forwarded-For`.
- Hostname `litebrite` does NOT resolve from Mac — always use IP `10.0.0.81` for SCP/SSH.
- SSH key: `~/.ssh/pixelwave_key` works for both Pi A (10.0.0.81) and Pi B (10.0.0.8). Always use `-i ~/.ssh/pixelwave_key` for SSH/SCP to either Pi.

## Deploy Flow

**Workflow:** Make changes → SCP template(s) to Pi for instant preview → user says "commit" → commit + push. Restart only needed when `main.py` changes.

- NEVER auto-commit. Only commit when user explicitly says "commit".
- After changes, open Safari to the relevant `pigarage.com` page.
- SCP templates directly for preview (Jinja2 serves from disk, no restart needed).
- `main.py` changes require `sudo systemctl restart livedoodle`.

```bash
# SCP a template (instant, no restart)
scp -i ~/.ssh/pixelwave_key templates/home.html karltkurtz@10.0.0.81:~/livedoodle/templates/home.html

# SCP main.py + restart
scp -i ~/.ssh/pixelwave_key main.py karltkurtz@10.0.0.81:~/livedoodle/main.py
ssh -i ~/.ssh/pixelwave_key karltkurtz@10.0.0.81 "sudo systemctl restart livedoodle"

# Commit + push (after user approves)
git add <specific files> && git commit -m "message"
git push

# Deploy from Pi (full pull)
ssh -i ~/.ssh/pixelwave_key karltkurtz@10.0.0.81 "cd ~/livedoodle && git pull && sudo systemctl restart livedoodle"
# Pi ALWAYS has local changes from SCPs — use git stash first:
ssh -i ~/.ssh/pixelwave_key karltkurtz@10.0.0.81 "cd ~/livedoodle && git stash && git pull && sudo systemctl restart livedoodle"
```

⚠️ **SCP gotcha:** When SCP-ing multiple files to different destinations, use separate SCP commands. `scp file1 file2 host:dir/` puts both in the same directory — a template sent to `~/livedoodle/` instead of `~/livedoodle/templates/` will be silently ignored.

## Pi A Service

```bash
sudo cp livedoodle.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable livedoodle && sudo systemctl start livedoodle
sudo journalctl -u livedoodle -f
```

## Pi A Chromium Kiosk

When the Pi boots, it loads the drawing canvas (`/display`) in Chromium kiosk mode — this is the intended behavior. The `/display` page shows the live artboard with full stroke history replay.

Autostart at user level: `~/.config/lxsession/LXDE-pi/autostart`

```
@xset s off
@xset -dpms
@xset s noblank
@bash -c 'sleep 5 && chromium --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble http://localhost:8000/display'
```

`sleep 5` is required — Chromium launches before FastAPI is ready without it. Manual launch:

```bash
ssh karltkurtz@10.0.0.81 "DISPLAY=:0 chromium --kiosk http://localhost:8000/display &"
```

## Push Notifications (ntfy)

Drawing and guestbook submissions fire fire-and-forget push notifications via `https://ntfy.sh`.

- **Drawing submitted:** topic `livedoodle-drawing-submission`, title "New drawing submitted", body: `Name from Location — Xm Ys`
- **Guestbook signed:** topic `livedoodle-guestbook-submission`, title "New guestbook entry", body: `Name from Location: message text...`
- Implemented in `main.py` via `_notify_ntfy(message, topic, title)` called with `asyncio.create_task` (never blocks the WS handler)
- `httpx` is already a dependency (used for camera polling) — no new packages needed

## Open Graph

- `og-image.png` (639×507) committed to repo and served at `/og-image.png`
- OG + Twitter card meta tags in `home.html` point to `https://pigarage.com/og-image.png`

## Draw Page — Stamp / Picker Architecture (draw.html)

Pickers (SHAPES, EMOJI, QUOTES) use `position: fixed` overlay modals with class `.picker-overlay` / `.picker-overlay.visible`. BRUSH expands inline via `#brush-picker.open`.

Stamp flow:
1. User selects shape/emoji/quote/image → `placeStamp(dataUrl, szW, szH)` called
2. Stamp appears on canvas via `#stamp-overlay` (position: absolute, inset: 0, z-index: 10 inside `#canvas-wrapper`)
3. User drags/resizes/rotates stamp using handles
4. `#stamp-controls` (REMOVE/KEEP) becomes visible via `visibility: visible` — always in layout to prevent canvas height shift
5. Toolbar dims to 5% opacity via `#toolbar.stamp-mode`
6. KEEP commits stamp to canvas and sends `{type:"stamp", ...}`; REMOVE discards

`renderQuote(text)` — async, awaits `document.fonts.load()` before measuring/drawing so Comic Neue is ready on mobile. Renders at 3× resolution, returns `{ dataUrl, ratio }` so stamp isn't stretched. Font: `'Comic Neue'` (loaded from Google Fonts) → `'Comic Sans MS'` → `cursive`.
`placeStamp(dataUrl, szW, szH=szW)` — szH defaults to szW (square) for shapes/emoji.

## Visitor Heatmap (`/heatmap`)

- New page added at `GET /heatmap` and `GET /visitors`
- `main.py` tracks unique visitor IPs with lat/lon/city/region/country via ip-api.com
- Stored in `visitors.json` (max 500 entries)
- `heatmap.html`: equirectangular world map canvas, glowing teal dots per visitor, top regions/countries bar charts
- Nav button on home.html: full-width amber "VISITOR HEATMAP" button below GUESTBOOK/PAST ARTWORK

## Daily Drawing Prompt

- `main.py` has 100-item `PROMPTS` list and `get_daily_prompt()` using `date.toordinal() % len(PROMPTS)`
- Prompt passed to `draw.html` via Jinja2 as `{{ prompt }}`
- Shown in `#prompt-bar` between timer and canvas: "DAILY DRAWING CHALLENGE: [prompt]"

## Planned / TODO

- **START HERE NEXT TIME:** Fix fill tool on Pi LCD (see Fill Tool section above for next debugging steps)
- Replace Venmo placeholder in `donate.html` with real username
- Remove or protect old unauthenticated `POST /set-home` and `POST /set-away` endpoints
