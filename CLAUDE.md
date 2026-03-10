# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run dev server (with hot reload) — Mac requires Python 3.12+ (main.py uses X|Y union types)
/opt/homebrew/bin/python3.12 -m uvicorn main:app --reload

# Run production-style (matches Pi A service)
uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers

# Install dependencies (Mac)
/opt/homebrew/bin/pip3.12 install --break-system-packages -r requirements.txt
```

No build step. No Node. No npm.

## Architecture

Single-file FastAPI server (`main.py`) with Jinja2 templates.

### Routes

| Route | Description |
|-------|-------------|
| `GET /` | Home page — branding, MJPEG livestream, DRAW! button, presence status |
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
| `GET /stream` | MJPEG stream proxied from Pi B — persistent multipart response, one connection per viewer; replaces old `/snapshot` polling |
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

// View → server (chat message from a viewer)
{"type": "chat", "text": "hello!"}

// Server → all view clients (broadcast chat message)
{"type": "chat", "text": "hello!", "from": "BROOKLYN, NY, US"}
```

**Chat rate limiting:** `CHAT_RATE_LIMIT = 3.0` seconds per view connection (tracked in `manager._view_last_chat`). Text truncated to 200 chars server-side. `from` label is ip-api.com geo string uppercased; falls back to `"VISITOR"` if no geo data.

### Coordinates and Sizing

All stroke coordinates and stamp positions/sizes use **normalized values** (0.0–1.0) relative to canvas dimensions.

**Stroke size** is also normalized: stored as `brushSize / canvas.width`. When rendering, multiply by the target canvas width. This ensures consistent visual thickness across phone, Pi display, and artwork cards.

**Backward compatibility:** Old strokes (before normalization) have `size >= 1` (absolute pixels). New strokes have `size < 1` (normalized). Renderers check `s.size >= 1 ? s.size : s.size * canvasWidth`.

### State

`ConnectionManager.history` holds all strokes/stamps/fills since the last clear. Resets on clear. New clients receive the full history as a single `sync` message.

`_last_visitor_time: float` — updated whenever a draw client connects, sends a heartbeat or stroke, or the home page polls `/status`. Used by `/display` to decide when to show the screensaver.

`_artwork_editing: bool` — set `True` by `POST /artwork/edit-start`, `False` by `POST /artwork/edit-end`. Included in `/status` so the home page PAST ARTWORK button disables cross-device when the admin is in edit mode.

`manager._client_ips: dict[int, str]` — maps `id(websocket)` → IP string for both draw and view clients; used to look up geo for DRAW! button location and chat sender labels.
`manager._view_last_chat: dict[int, float]` — maps `id(websocket)` → last chat timestamp for rate limiting.

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
artwork_history.json       # Flat JSON array of saved artwork entries (max 100)
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
- DRAW! button amber when busy (someone else drawing), shows countdown timer and drawer's city/region/country
- Corner-bracket frame around livestream via `::before`/`::after` pseudo-elements on `#stream-frame` and `#stream-inner`
- Livestream `<img>` src points to `/stream` (MJPEG); browser maintains one persistent connection and renders frames natively — no JS polling loop
- Reaction buttons (emoji burst) disabled (opacity 0.35, grayscale) when no draw session active; enabled when session starts via `/status` poll
- **Chat panel:** collapsible below livestream, viewers-only; `#chat-toggle` button sits between stream and panel with `border-top: none`; button says "OPEN CHAT" / "CLOSE CHAT"; unread count shown in green as `[N NEW]` when panel is closed and messages arrive; max 10 messages (oldest drops); 3s rate limit per connection; geo-labeled senders (city/region/country, no "VIEWER FROM" prefix); session-only (in-memory, no persistence); iOS Safari zoom prevented via `font-size: 16px` on input

**Draw page specifics:**
- Timer bar below canvas, 36px coral countdown
- Slider rail white, amber square thumb
- Stamp buttons: REMOVE (coral) and KEEP (green) — appear as a fixed-size amber-bordered popup centered in the toolbar; toolbar dims to 5% opacity when stamp mode is active; uses `visibility` (not `display`) so toolbar height never shifts and canvas never clips
- FILL button present in toolbar but currently disabled — shows amber toast "THE FILL BUTTON IS BEING WORKED ON." for 3s on tap; fill infrastructure is fully wired (see Fill section below)
- SHAPES, EMOJI, QUOTES pickers open as full-screen overlay modals (dark backdrop, centered panel); BRUSH expands inline
- Picker toggle buttons: SHAPES=purple (72px), BRUSH=teal (72px), EMOJI=amber (72px), QUOTES=coral (72px)
- Each picker popup has a colored border matching its button: SHAPES=purple (`--purple`, `rgba(191,95,255,0.3)` glow), EMOJI=amber (`--amber`, `rgba(255,179,0,0.3)` glow), QUOTES=coral (`--coral`, `rgba(255,74,42,0.3)` glow)
- All `#btn-row` buttons are permanently lit accent colors (never greyed out); have a CSS tap animation (`@keyframes btn-tap`) on `pointerdown`
- Daily drawing prompt shown between timer bar and canvas: "DAILY DRAWING CHALLENGE: [prompt]" — rotates daily via `date.toordinal() % len(PROMPTS)` in `main.py`
- Triangle shape button label is "TRIANGLE" (not "TRI")
- Color palette: 11 swatches — black `#000000`, gray `#888888`, white `#ffffff`, brown `#8b4513`, red `#e63333`, orange `#e67c33`, yellow `#e6d633`, green `#33c44a`, blue `#3399e6`, indigo `#4b0082`, violet `#8b00ff`
- Active swatch scales to 1.5× (`transform: scale(1.5)`); swatch gap is 10px; swatch size is 26×26px
- Amber toolbar accent line (`#toolbar::before`) sits at `top: -22px`
- SHAPES/BRUSH/EMOJI/QUOTES row (`#tools-section`) has `margin-top: -60px` to pull it up toward the swatches; note: an invisible `#stamp-controls` div (~50px tall, `visibility: hidden`) sits between `#swatches` and `#tools-section` in the DOM, so large negative margins are needed to visibly close that gap

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
- `httpx` is already a dependency (used for MJPEG stream proxy) — no new packages needed

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

### START HERE NEXT TIME
**LLM moderation is live and working. Next two priorities:**

1. **Admin moderation log view** — read-only panel in `/admin` showing `moderation_log.json` entries (timestamp, reason, IP). No actions needed, just visibility.
2. **Moderation confidence threshold** — after the main pass returns `flagged: true`, run a second prompt asking confidence 1–10; only hard-flag on 7+. Prevents false positives on ambiguous drawings.

---

**Merge `chat-feature` branch.** Chat feature is complete and committed on `chat-feature` branch. When ready, merge into `main` and deploy to Pi.

**Fix fill tool on Pi LCD.** Flood fill works on draw.html (user sees it) and saves to artwork correctly, but does NOT render on the Pi display. See the Fill Tool section for full context. Next things to try:
- SSH to Pi, open browser dev tools, check for JS errors during fill
- Test if `ctx.getImageData` returns correct data on Pi by logging pixel values
- Try wrapping `floodFill` call in `requestAnimationFrame` in display.html to flush GPU before pixel read
- Check if Pi's Chromium version has known `getImageData` bugs on hardware-accelerated canvases
- Consider sending fill result as a full canvas snapshot (dataURL stamp) instead of re-computing flood fill on display

### Recently Completed
- ~~LLM content moderation~~ — Groq vision API (`meta-llama/llama-4-scout-17b-16e-instruct`), 3-pass, PIL renderer, submission-time only (no polling loop), whoops screen + countdown, artboard clear on flag, ntfy push on flag, silent artwork delete, `moderation_log.json`
- ~~Fix draw session race condition~~ — server sends `{type:"busy"}` and closes on duplicate draw connect; home.html renders button state server-side; draw.html shows busy screen if rejected
- ~~Increase `MAX_ARTWORK` to 100~~ — done, drops oldest when full
- ~~Heatmap continent/country outlines~~ — topojson-client + world-atlas from jsDelivr CDN
- ~~Heatmap HOME button moved to upper-right nav~~
- ~~Eraser cursor~~ — custom SVG eraser cursor when eraser tool is active; resets on swatch click
- ~~Picker popup colored borders~~ — SHAPES=purple, EMOJI=amber, QUOTES=coral
- ~~Color palette reduced to 11~~ — black, gray, white, brown, red, orange, yellow, green, blue, indigo, violet
- ~~Active swatch scales to 1.5×~~ — deselects back to 1×
- ~~Tri-state presence system~~ — home / away / coding (replaces bool `_is_home`); coding state has pulsing amber animation on home page, right-aligned
- ~~DRAW! button shows drawer location~~ — "SOMEONE IN BROOKLYN, NY IS DRAWING" (server-rendered + JS-updated via `/status`); falls back to "SOMEONE IS DRAWING" if no location
- ~~Reaction buttons disabled when no session active~~ — opacity 0.35 + grayscale; enabled when draw session detected via `/status` poll
- ~~Livestream cache-bust~~ — replaced by MJPEG stream; no polling or cache-busting needed
- ~~Switch livestream from JS polling to MJPEG proxy~~ — done; `/stream` proxies MJPEG from Pi B, one persistent connection per viewer
- ~~Live chat feature~~ — collapsible panel on home page, viewers-only, geo-labeled, session-only, 3s rate limit, 10 message cap, unread counter in green on OPEN CHAT button
- ~~Removed tagline~~ — "// real strokes · real screen · no signup" paragraph removed from home page

### Bugs / Edge Cases to Watch
- **Toolbar layout fragility** — `margin-top: -60px` on `#tools-section` is a workaround for phantom `#stamp-controls` height (visibility:hidden but still in layout); if layout shifts unexpectedly, this is why
- **DRAW! button location text** — location comes from ip-api.com at draw connect time; if lookup fails or IP is private, location is blank and button falls back to "SOMEONE IS DRAWING" gracefully
- **Old unauthenticated endpoints** — `POST /set-home` and `POST /set-away` still exist without password protection; low risk but should be removed or gated

### Backlog
- Replace Venmo placeholder in `donate.html` with real username
- Remove or protect old unauthenticated `POST /set-home` and `POST /set-away` endpoints
- **Auto-expire draw session on heartbeat timeout** — ~~done~~ already fixed (45s expiry); watch for edge cases
- **GIF/video playback from admin page** — upload a GIF on the admin page, play it to the display as ephemeral stamps. `pillow` is already in `requirements.txt`. MP4 needs `opencv` on Pi. `play_gif.py` on Desktop is the working CLI prototype. Needs: `POST /admin/play-gif`, `POST /admin/stop-gif` in `main.py`, and a section in `admin.html`.

### YouTube Livestream Prototype (Mac-only, not deployed)
**Purpose:** Fallback plan in case Cloudflare throttles the MJPEG stream at scale. Build a local prototype on Mac to evaluate YouTube Live as an alternative before needing it in production.

**Plan:**
1. Create a YouTube Live stream and get a stream key
2. Use OBS or ffmpeg on Mac to push Mac webcam to YouTube via RTMP
3. Swap `<img id="stream">` in a local copy of `home.html` with a YouTube iframe embed
4. Run the FastAPI server locally and test the full experience

**Key tradeoff to evaluate:** YouTube's low-latency mode is ~3–5s, ultra-low is ~1–2s. The prototype's main purpose is to *feel* whether that delay kills the live drawing experience (someone watching strokes appear with a 2s lag).

**Important:** This is a Mac-only prototype, never deployed to Pi. Keep it as a contingency. The current MJPEG approach is preferred — it's lower latency, more personal, and has no third-party player UI. Only switch if Cloudflare becomes a real problem.

### New Feature Ideas
- **Reactions** — home page visitors send live emoji reactions (heart, fire, etc.) that briefly appear on `/display`
- **Rooms / concurrent canvases** — multiple channels people can choose from
- **WebRTC audio** — drawer can optionally unmute and talk while drawing (like Jackbox)
- **Multiplayer games** — e.g. tic-tac-toe on the canvas
- **ntfy notifications for donations** — fire a push notification when someone donates
- **Fill cursor** — when FILL tool is selected, change mouse cursor to a bucket icon (mirrors eraser cursor feature)
- **Holiday/seasonal site-wide background** — background changes based on current holidays or events
- **Holiday welcome message on home page** — reflect current holidays/events in the home page greeting
- **Seasonal art and themes on /draw** — special stamps, colors, or prompts active only during specific dates/seasons/holidays

---

## Session Wrap-Up (2026-03-08)

### Accomplished
- **Fill tool fixed and enabled** — was disabled with a toast; now works. Root cause: `getImageData` fails silently on Pi's hardware-accelerated Chromium canvas. Fix: after flood fill runs locally in draw.html, the canvas is exported as a JPEG stamp and sent as `{type:"stamp", ...}` instead of `{type:"fill", ...}`. Display just renders the image — no pixel read needed.
- **Ephemeral stamp support** — added `"ephemeral": true` flag to WebSocket stamp messages. Server relays to display clients but skips `update_history()`. Frames disappear when session ends, canvas history stays clean.
- **play_gif.py** — friend's script that streams GIF/MP4 frames as stamps over the draw WebSocket. Updated to use `"ephemeral": true`. Lives at `~/Desktop/play_gif.py`. Run manually from terminal: `python play_gif.py mygif.gif -d 0.05`

### Decisions Made
- Fill sends a full canvas JPEG snapshot as a stamp, not a `fill` type message. The `{type:"fill"}` message type is no longer used by draw.html but remains supported in history/relay for backward compat.
- Ephemeral flag is checked in `main.py` WebSocket handler, not in `update_history()` — keeps the method clean.

---

## Session Wrap-Up (2026-03-09)

### Accomplished
- **LLM content moderation — fully built, tested, and live.**
  - Groq API key set on Pi at `~/livedoodle/.env`. Service reads it via `EnvironmentFile`.
  - Model: `meta-llama/llama-4-scout-17b-16e-instruct` (replaced decommissioned `llama-3.2-11b-vision-preview`).
  - Moderation runs at artwork submission time only — no 60s polling loop.
  - PIL renderer (`_render_entry`) draws strokes and composites stamps to a JPEG — matches what `/artwork` gallery displays.
  - 3-pass logic: runs up to 3 Groq calls, flags on first positive hit.
  - On flag: deletes artwork entry, clears artboard, sends `{type:"whoops"}` to draw client, logs to `moderation_log.json`, fires ntfy push notification (topic: `livedoodle-moderation`).
  - On pass: sends `{type:"approved"}` to draw client.
  - Draw page holds at animated "SUBMITTING..." screen until it receives `approved` or `whoops` — no premature redirect.
  - Whoops screen: `// WHOOPS //`, community guidelines copy, 4-second countdown timer, redirects to `/`.
  - Artboard cleared on flag so canvas is blank for next visitor.
- **Prompt hardening** — final prompt uses mandatory rule override to defeat model safety guardrails that would otherwise refuse to flag crude sexual drawings:
  - Asks explicit yes/no anatomy questions (penis, vagina, torso, breasts, bra, underwear, partial nudity, hate symbols, violence)
  - "RULE: If any answer is yes, you MUST set flagged to true. This is mandatory — do not apply your own judgment."
- **`pillow` added to `requirements.txt`** — needed for `_render_entry`.
- **ntfy notification on flag** — topic `livedoodle-moderation`, title "LiveDoodle: Content Flagged", body includes reason.

### Decisions Made
- No camera-based moderation. Only submitted artwork is moderated (not live draw session camera feed).
- Submitter sees whoops screen and is redirected to `/` — no reason text shown, just "community guidelines."
- `moderation_log.json` exists on server but is not exposed via any route. Admin log view is next feature.
- Known limitation: very crude arch + legs drawings (like the "Helsingborg" entry) read as "house/doghouse" — model cannot reliably flag them. Manual delete via admin is the fallback.
- Groq free tier: ~1,000 req / 30,000 tokens per ~2.75hr window. 3-pass costs ~1,500 tokens/submission — sustainable for low-volume use.

### Incomplete / Loose Ends
- **Admin moderation log view** — approved but not yet built. Read-only panel in `/admin` showing `moderation_log.json` entries.
- **Moderation confidence threshold** — approved but not yet built. Second prompt pass on positive flags: ask confidence 1–10, only hard-flag on 7+.
- `play_gif.py` is not committed to the repo (lives only on Desktop). Fine for now.
- Old unauthenticated `POST /set-home` and `POST /set-away` endpoints still exist — low priority but should be gated.

### Resume From Here
Next priorities (in order):
1. **Admin moderation log view** — add read-only section to `admin.html` that fetches and renders `moderation_log.json` entries. Backend: new `GET /admin/moderation-log` route (password-protected).
2. **Moderation confidence threshold** — in `_moderate_frame()`, after a `flagged: true` result, fire a second Groq call asking confidence 1–10; only return flagged if ≥ 7. Reduces false positives.
3. **GIF playback from admin page** — `pillow` is already in requirements. Add `POST /admin/play-gif` + `POST /admin/stop-gif` to `main.py`, add section to `admin.html`.

---

## Session Wrap-Up (2026-03-10)

### Accomplished
- **SQLite moderation log in admin** — replaced flat JSON with `moderation.db` (stdlib `sqlite3`); sortable/searchable table in `/admin` (sort by timestamp/name/IP/location/reason; client-side filter). `GET /admin/moderation-log` route (password-protected).
- **Fill mode toolbar dimming** — when FILL active, all other buttons dim + `pointer-events:none`; slider/label dim; swatches stay active. Same pattern added for ERASER (`eraser-mode` class).
- **Pulsing glow on active FILL/ERASER** — teal pulse for ERASER, green pulse for FILL (1.4s ease-in-out infinite).
- **Fill bucket cursor** — SVG paint bucket cursor via `encodeURIComponent()` when FILL is active.
- **Canvas max-width 960px** — draw page canvas capped at 960px wide on desktop.
- **Maze game** — merged to `main` and live on pigarage.com.
- **Bomberman game** — full game built and live on `main`:
  - Procedural grid: indestructible walls at even row+col intersections, soft blocks (amber brick) at ~65% of other cells
  - Player (amber circle with head/eyes) starts at (1,1); moves one cell at a time via d-pad or arrow keys
  - BOMB button (coral) appears in d-pad row; spacebar also works on desktop
  - Bombs: 2.5s fuse, pulsing animation; explosion range 3 (upgradeable); chain reactions
  - Flames: 550ms duration, color-fades from yellow→orange→coral
  - Powerups: **+B** (amber, +1 bomb capacity) and **+F** (coral, +1 flame range) hidden under ~25% of soft blocks; revealed when block destroyed; walk over to collect
  - Hidden exit (green ▶) under a soft block near far corner; revealed on destruction; walk onto it to win
  - HUD: `BOMBS x?` / `FLAME x?` in bottom-left
  - Game over: GAME OVER screen (coral) + 4s countdown; win: YOU WIN! screen (green) + 5s countdown; both restore artwork and resync display
  - `bDirty` flag + 8fps cap for display sends (event-driven: sends on move/bomb/explosion/flame-expire only)
- **GAMES button animation** — pulsing purple glow (1.8s) + blinking coral NEW badge; stops when picker is opened
- **LCD white flash fix (partial)** — two causes addressed:
  1. Ephemeral stamps were pushed into `history` on `display.html` → `redraw()` cascade on sync → white flash. Fixed: ephemeral stamps bypass history entirely, drawn directly.
  2. 20fps JPEG spam overloaded Pi WebSocket → disconnect → reconnect → sync → `redraw()` → white. Fixed: event-driven sends with `bDirty` flag + 8fps cap + lower JPEG quality (0.55).
  - **Still some occasional white flashes remain** — suspected cause: WebSocket reconnects under load still happening, or `redraw()` being triggered by other events (e.g. artwork sync on new viewer connect). Not fully resolved.

### Decisions Made
- `maze-game` branch merged to `main` and deployed.
- Game frames are event-driven, not tick-driven, for display sends. Local canvas still animates at full rate for player.
- Bomberman is single-player only for now (no enemies). Enemies deferred.
- Mac dev server requires Python 3.12+ (`main.py` uses `X | Y` union syntax); Mac system Python is 3.9. Use `/opt/homebrew/bin/python3.12 -m uvicorn main:app --reload`.

### Incomplete / Loose Ends
- **LCD white flash not fully fixed** — occasional flashes still reported. Likely WebSocket reconnects on the Pi. Next things to try:
  - Investigate if Pi WebSocket disconnects during game (check Pi logs: `sudo journalctl -u livedoodle -f`)
  - Consider further reducing game frame JPEG size or quality
  - Consider a debounced `redraw()` on display.html that delays clear until images are ready (double-buffer)
  - Consider changing `clearCanvas()` to fill `#0a0a0a` instead of white so flashes are black (invisible)
- **Moderation confidence threshold** — still not built (carry over).
- **GIF playback from admin page** — still not built (carry over).
- Old unauthenticated `POST /set-home` and `POST /set-away` still exist.
- **Bomberman enemies** — deferred. Simple wandering AI is the next step once flash is resolved.

### Resume From Here
1. **Fix LCD white flash completely** — change `clearCanvas()` to black as a quick win; then investigate Pi WS reconnects.
2. **Bomberman enemies** — simple wandering AI, game over on contact.
3. **Moderation confidence threshold** — second Groq pass on positive flags (confidence 1–10, only flag if ≥ 7).
4. **GIF playback from admin page** — `POST /admin/play-gif` + `POST /admin/stop-gif`.

---

## Session Wrap-Up (2026-03-11)

### Accomplished
- **WARGAME built and deployed** — WarGames-inspired text adventure inside `/draw`, accessible via the GAMES picker.
  - Full state machine: BOOT → LOGIN → SIDE_SELECT → TARGET_SELECT → LAUNCH_CONFIRM → MISSILES_AWAY → RETALIATION → AFTERMATH → LESSON
  - Boot sequence scrolls WOPR computer lines at 300ms/line
  - Side selection: USA targets USSR cities, USSR targets US cities
  - Target selection: sequential "SELECT FIRST/SECOND/THIRD TARGET" prompts; selected targets get `[X]` strikethrough in dim green with a canvas strikethrough line; only unselected targets remain as buttons
  - Launch confirmation, missile arc animation (stepping `wgMissileProg` via `setInterval`), retaliation, casualty totals, WarGames lesson quote
  - LESSON screen shows PLAY AGAIN button to restart
  - All input via buttons (no text field) — buttons rebuilt dynamically by `wgUpdateUI()` after every state transition via `wgDispatch(input)`
  - EXIT GAME button in the dpad row; dpad arrows and BOMB button hidden in wargame mode
- **dpad z-index fix** — `#toolbar::before` amber line (positioned `top: -22px`) was painting over the dpad and eating all clicks for all games. Fixed with `position: relative; z-index: 2` on `#dpad`. This also fixed maze and Bomberman dpad being unresponsive.
- **Cleaned up `maze-game` branch** — deleted after confirming merged to `main`.

### Decisions Made
- WARGAME uses the same ephemeral stamp pattern as Maze and Bomberman (canvas frames sent as `{ephemeral:true}` stamps, never saved to artwork history).
- All WARGAME interaction is button-driven. No text input field. `wgDispatch(input)` → `wgHandleInput(input)` → `wgUpdateUI()` → `wgRender()` + `wgSendFrame()`.
- `wgUpdateUI()` rebuilds the button bar from scratch on every call; buttons are created with `wgMakeBtn(label, cb, red?)`.
- NO in LOGIN → `endWargame()` (labeled "NO — EXIT"). NO in LAUNCH_CONFIRM → abort back to TARGET_SELECT (labeled "NO — ABORT").

### Incomplete / Loose Ends
- **LCD white flash** — still occasional; carry over from last session.
- **Bomberman enemies** — deferred, carry over.
- **Moderation confidence threshold** — carry over.
- **GIF playback from admin page** — carry over.

### Resume From Here
1. **New games** — see ideas below. Snake is the best next pick (dpad-native, simple state).
2. **Bomberman enemies** — simple wandering AI.
3. **LCD white flash** — investigate Pi WS reconnects; consider black `clearCanvas()`.
4. **Moderation confidence threshold** — second Groq pass, flag only if ≥ 7.

### Game Ideas for Future Sessions
- **Snake** — dpad moves head, grows on eat, dies on self/wall collision. Easiest next game. Apple spawns randomly, score shown in HUD.
- **Pong** — single-player vs CPU. Dpad up/down moves paddle. CPU paddle tracks ball with slight lag. Ball speeds up over time.
- **Breakout** — dpad left/right moves paddle. Bricks arranged in rows with color tiers. Ball bounces, clears bricks. Classic.
- **Tic-Tac-Toe** — 9 numbered buttons for grid positions. Player is X, CPU picks random open square. Simple but interactive.
- **2048** — dpad swipes merge numbered tiles. Pure grid logic, no animation needed. Could send a frame per move.
- **Simon Says** — 4 colored buttons flash in sequence; player must repeat. Memory game. Buttons are the entire UI.
