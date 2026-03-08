# LiveDoodle — How to Build This

This guide explains how to rebuild LiveDoodle from scratch. LiveDoodle is a real-time drawing app: visitors draw on their phones and the drawing appears live on a 7" display connected to a Raspberry Pi.

---

## What It Does

- A public website lets anyone visit and tap DRAW! to start drawing on a canvas
- Their strokes appear in real time on a physical display (a Raspberry Pi with a screen) sitting somewhere in your home
- A second Raspberry Pi with a camera streams a live photo of the display back to the website, so web visitors can watch it update
- Finished drawings are saved to a gallery at /artwork
- Visitors can sign a guestbook at /guestbook
- An admin panel at /admin lets you control the camera, toggle your presence status, and manage content

---

## Hardware Required

### Pi A — Server + Display Pi
- Raspberry Pi 4 (2GB or 4GB RAM recommended)
- Official Raspberry Pi 7" Touchscreen Display (800x480)
- MicroSD card (32GB+)
- USB-C power supply (5V 3A)
- Case with display mount (optional but recommended)

### Pi B — Camera Pi
- Raspberry Pi 4 (1GB is fine)
- Raspberry Pi HQ Camera Module (12MP)
- Camera lens (16mm telephoto works well for pointing at a display from ~2 feet away)
- MicroSD card (16GB+)
- USB-C power supply
- Camera mount or stand

### Networking
- Both Pis on the same local network (wired or WiFi)
- A Cloudflare account (free tier) for the public tunnel — this gives you a real HTTPS URL without port forwarding

### Optional
- A Venmo account if you want to accept donations
- ntfy.sh account (free) for push notifications when someone draws or signs the guestbook

---

## Software Stack

- **Python 3.11+** — the only language used
- **FastAPI** — web framework, handles HTTP routes and WebSockets
- **Uvicorn** — ASGI server that runs the FastAPI app
- **Jinja2** — HTML templating (renders server-side variables into HTML files)
- **httpx** — makes HTTP requests from the server (used for camera polling and push notifications)
- **Cloudflare Tunnel** — exposes your Pi to the internet without port forwarding
- No Node.js, no npm, no build step

---

## File Overview

### `main.py`
The entire backend. One Python file that does everything:
- Defines all URL routes (/, /draw, /display, /artwork, /guestbook, /admin, etc.)
- Manages WebSocket connections between draw clients and the display
- Keeps a history of strokes so new display clients get a full replay
- Saves and loads artwork entries, guestbook entries, presence status, and visitor data from JSON files
- Polls the camera Pi every 100ms and caches the latest JPEG frame
- Sends push notifications via ntfy.sh when drawings or guestbook entries are submitted
- Tracks visitor IPs with geolocation for the heatmap

**AI prompt to build this:**
"Build a single-file FastAPI server in Python. It should serve a home page, a mobile drawing canvas at /draw, and a display page at /display. Use WebSockets to relay drawing strokes from draw clients to display clients in real time. Keep a history of strokes in memory so new display clients receive a full replay on connect. Add a /snapshot route that polls a JPEG stream from a remote URL every 100ms and caches the frame. Save completed drawings as JSON to a file, capped at 100 entries. Include a password-protected admin route. Use Jinja2 for HTML templates."

---

### `templates/home.html`
The public-facing home page. Shows:
- The site name and a blinking dot
- A live snapshot of the display (polling /snapshot every 100ms)
- A DRAW! button that links to /draw (shows a countdown timer if someone else is drawing)
- Your presence status (I AM HOME / I AM AWAY)
- Links to guestbook, past artwork, visitor heatmap

**AI prompt:**
"Build an HTML page for a live art display website. Use Share Tech Mono font. Dark background (#0a0a0a). Retro arcade aesthetic with neon glow effects. Show a live camera feed that polls /snapshot every 100ms. Show a DRAW! button that polls /status every 500ms — if someone is actively drawing, show a countdown timer and disable the button. Include a pixel starfield animation (40 small squares drifting upward) on a fixed canvas behind everything. Use CSS scanlines overlay for CRT effect."

---

### `templates/draw.html`
The mobile drawing canvas. This is the most complex template:
- Full-screen canvas for drawing
- Color swatch palette
- Brush size slider
- ERASER, UNDO, CLEAR, DONE buttons
- SHAPES, EMOJI, QUOTES, BRUSH picker buttons that open overlay popups
- A countdown timer bar at the top (5 minutes per session)
- Sends strokes to the server via WebSocket in real time
- Stamp system for placing shapes, emoji, quotes, and uploaded images onto the canvas

**AI prompt:**
"Build a mobile-optimized drawing canvas in HTML/JS. Use a WebSocket to send stroke data to a server in real time. Normalize all coordinates (0.0 to 1.0) relative to canvas size. Include a color palette, brush size slider, eraser, and undo. Add a 5-minute countdown timer. Add picker buttons (SHAPES, EMOJI, QUOTES) that open full-screen overlay modals. Include a stamp system where the user can place an image on the canvas and drag/resize/rotate it before committing. Use Share Tech Mono font, dark retro aesthetic, amber toolbar."

---

### `templates/display.html`
The Pi kiosk page — zero UI, just the canvas:
- Connects to the server via WebSocket as a display client
- Replays full stroke history on connect
- Renders all new strokes in real time
- Screensaver activates after 20 seconds of no visitor activity (polls /activity)
- No controls, no buttons — Chromium runs this in fullscreen kiosk mode

**AI prompt:**
"Build a fullscreen HTML canvas page with no UI. Connect to a WebSocket server and replay incoming stroke history. Handle stroke, stamp, fill, clear, sync, and reload message types. After 20 seconds of inactivity (polled from a /activity endpoint), show a screensaver overlay with a slow drifting animation to prevent display burn-in. Hide the cursor by default."

---

### `templates/artwork.html`
The past artwork gallery:
- Fetches saved artwork entries from /artwork/entries
- Renders each entry as a canvas by replaying its stroke history
- Shows the artist name, location, time, and drawing duration
- Clicking an entry opens a fullscreen lightbox
- Edit mode (accessed from admin) shows delete buttons on each card

**AI prompt:**
"Build an HTML gallery page that fetches a JSON list of drawing entries from /artwork/entries. Each entry contains an array of stroke objects. Render each entry onto a canvas by replaying the strokes. Show metadata (name, location, date, duration) below each canvas. Add a lightbox that opens on click. Include an edit mode where each card shows a delete button."

---

### `templates/guestbook.html`
A simple guestbook:
- Shows all entries (name, location, message, date)
- Form to submit a new entry (name + message, 200 char limit)
- Entries are stored server-side

**AI prompt:**
"Build an HTML guestbook page. Fetch entries from /guestbook/entries and display them as a list with name, location, date, and message. Include a form at the top that POSTs to /guestbook/sign. Use Share Tech Mono font, dark retro aesthetic, purple accent color."

---

### `templates/admin.html`
Password-protected admin panel:
- Login form that stores the password in memory (never sent to localStorage)
- Live camera preview (1fps)
- Camera controls (brightness, contrast, saturation, exposure, gain) with debounced sliders
- Presence toggle (I AM HOME / I AM AWAY)
- Buttons to clear all guestbook entries or all artwork
- Button to navigate to artwork edit mode

**AI prompt:**
"Build a password-protected admin panel in HTML. Show a login form first. On success, reveal sections for: live camera preview (polling an image endpoint at 1fps), slider controls for camera settings (debounced 120ms, sent via POST), presence toggle buttons, and dangerous action buttons (clear guestbook, clear artwork). Store the password in JS memory only — never in localStorage or cookies. Use Share Tech Mono font, amber accent."

---

### `templates/heatmap.html`
A visitor map:
- Fetches visitor data (lat/lon/city/country) from /visitors
- Renders an equirectangular world map on a canvas
- Draws country outlines using TopoJSON data from a CDN
- Places a glowing teal dot for each visitor
- Shows bar charts of top regions and countries

**AI prompt:**
"Build an HTML visitor heatmap page using a canvas element. Fetch visitor data (lat/lon/city/country) from /visitors. Draw an equirectangular world map: first a grid, then country outlines using topojson-client and world-atlas data from jsDelivr CDN, then a glowing dot for each visitor. Below the map, show bar charts of the top visitor regions and countries. Use Share Tech Mono font, teal accent, dark background."

---

### `templates/about.html` and `templates/donate.html`
Static informational pages. About explains the project and hardware. Donate has a Venmo link.

**AI prompt:**
"Build a simple informational HTML page using Share Tech Mono font with dark retro arcade aesthetic. Teal accent for about.html, coral accent for donate.html. Include the standard pixel starfield and scanlines."

---

### `artwork_history.json`
Flat JSON array of saved artwork entries. Each entry looks like:
```json
{
  "history": [ ...stroke objects... ],
  "name": "Karl",
  "location": "Austin, Texas, US",
  "time": 1709123456.789,
  "duration": 183
}
```
Capped at 100 entries. Oldest is dropped when full. Created automatically by the server — do not edit by hand.

---

### `guestbook.json`
Flat JSON array of guestbook entries. Capped at 200. Same pattern as artwork_history.json.

---

### `home_status.json`
Single JSON object: `{"home": true}` or `{"home": false}`. Controls the I AM HOME / I AM AWAY status on the home page. Toggled via the admin panel.

---

### `visitors.json`
Flat JSON array of visitor records with IP, lat, lon, city, region, country. Capped at 500. Populated automatically when visitors load the home page.

---

### `requirements.txt`
Python dependencies:
```
fastapi
uvicorn[standard]
jinja2
python-multipart
httpx
```
Install with: `pip install -r requirements.txt`

---

### `livedoodle.service`
A systemd service unit file that runs the FastAPI server automatically on Pi A boot. Copy to `/etc/systemd/system/`, then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable livedoodle
sudo systemctl start livedoodle
```

**AI prompt:**
"Write a systemd service unit file that runs `uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers` as a service, working directory /home/youruser/livedoodle, restarting on failure."

---

## Setting Up Pi A (Server + Display)

1. Flash Raspberry Pi OS (64-bit, Desktop) to the SD card
2. Connect the 7" display
3. SSH in and clone your repo to `~/livedoodle`
4. Install Python deps: `pip install -r requirements.txt`
5. Install the systemd service (see above)
6. Set up Chromium to auto-launch in kiosk mode on boot by adding this to `~/.config/lxsession/LXDE-pi/autostart`:
   ```
   @xset s off
   @xset -dpms
   @xset s noblank
   @bash -c 'sleep 5 && chromium --kiosk --noerrdialogs --disable-infobars http://localhost:8000/display'
   ```
7. Install and configure Cloudflare Tunnel to expose port 8000 publicly

---

## Setting Up Pi B (Camera)

1. Flash Raspberry Pi OS (64-bit, Lite) to the SD card
2. Connect the HQ camera module
3. Write a small Python script (`stream.py`) using picamera2 that:
   - Serves JPEG snapshots at `http://0.0.0.0:8080/?action=snapshot`
   - Accepts POST requests to `/controls` for adjusting camera settings (brightness, contrast, saturation, exposure, gain)

**AI prompt for stream.py:**
"Write a Python HTTP server using picamera2 that serves a single JPEG snapshot at GET /?action=snapshot and accepts camera control adjustments via POST /controls (JSON body with keys: brightness, contrast, saturation, exposure, gain, auto). When 'auto' is true, recreate the camera to re-enable auto-exposure. Run on port 8080."

---

## Cloudflare Tunnel Setup

1. Create a free Cloudflare account and add your domain (or use a free .trycloudflare.com URL)
2. Install `cloudflared` on Pi A
3. Run `cloudflared tunnel login` and `cloudflared tunnel create livedoodle`
4. Configure the tunnel to point to `http://localhost:8000`
5. Set it to run as a service so it starts on boot
6. In `main.py`, use `--proxy-headers` with uvicorn so the real visitor IP comes through from Cloudflare headers

---

## Development Workflow

- Make changes locally on your Mac
- SCP templates directly to the Pi for instant preview (no restart needed for HTML/CSS/JS changes):
  ```bash
  scp templates/draw.html user@PI_IP:~/livedoodle/templates/draw.html
  ```
- Changes to `main.py` require restarting the service:
  ```bash
  scp main.py user@PI_IP:~/livedoodle/main.py
  ssh user@PI_IP "sudo systemctl restart livedoodle"
  ```
- Run locally for development:
  ```bash
  uvicorn main:app --reload
  ```

---

## Push Notifications (Optional)

Uses ntfy.sh (free, no account needed for basic use):
- When a drawing is submitted, POST to `https://ntfy.sh/your-topic-name`
- When a guestbook entry is submitted, POST to a different topic
- Subscribe to those topics in the ntfy mobile app to get notified

**AI prompt:**
"Add fire-and-forget push notifications to the FastAPI app using httpx. When a drawing is submitted, send a POST to https://ntfy.sh/my-drawing-topic with a title and body. When a guestbook entry is submitted, send to https://ntfy.sh/my-guestbook-topic. Use asyncio.create_task so it never blocks the WebSocket handler."
