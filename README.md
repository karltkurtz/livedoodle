# LiveDoodle

Real-time collaborative drawing app. Visitors draw on their phones and the result appears live on a 7" display attached to a Raspberry Pi.

## Hardware

- **Pi A (server):** Raspberry Pi 4 running the FastAPI server. A 7" display is attached and shows `/display` in Chromium kiosk mode.
- **Pi B (camera):** Raspberry Pi 4 with HQ camera pointed at Pi A's display. Streams whatever is drawn — no code changes needed on Pi B.
- Both Pis are connected via Ethernet. The app is exposed publicly via a Cloudflare tunnel at `pigarage.com`.

## Project Structure

```
livedoodle/
├── main.py               # FastAPI app + WebSocket server
├── templates/
│   ├── draw.html         # Mobile drawing canvas
│   └── display.html      # Pi A kiosk display (no UI)
├── requirements.txt
├── livedoodle.service    # systemd unit for Pi A
└── CLAUDE.md
```

## Local Development

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

- Drawing canvas: http://localhost:8000/draw
- Display page: http://localhost:8000/display

## Pi A Setup

```bash
# On Pi A
git clone https://github.com/<you>/livedoodle.git
cd livedoodle
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Install and start the service
sudo cp livedoodle.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable livedoodle
sudo systemctl start livedoodle
```

### Chromium kiosk mode (Pi A)

Add to `/etc/xdg/lxsession/LXDE-pi/autostart` (or equivalent):

```
@chromium-browser --kiosk --noerrdialogs --disable-infobars http://localhost:8000/display
```

## Deploy (after changes)

```bash
# On Mac — commit and push
git add -A && git commit -m "your message"
git push

# On Pi A — pull and restart
ssh pi@<pi-a-ip>
cd ~/livedoodle && git pull
sudo systemctl restart livedoodle
```

## Cloudflare Tunnel

The server binds to `0.0.0.0` and runs with `--proxy-headers` so it respects `X-Forwarded-For` headers from the Cloudflare tunnel. No additional configuration needed in the app.
