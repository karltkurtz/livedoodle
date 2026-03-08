import asyncio
import base64
import datetime
import ipaddress
import json
import os
import time
import httpx

# Load .env for local dev (systemd uses EnvironmentFile instead)
def _load_dotenv():
    if os.path.exists(".env"):
        with open(".env") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
_load_dotenv()
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

CAMERA_URL = "http://10.0.0.8:8080/?action=snapshot"
POLL_INTERVAL = 0.1  # seconds
ARTWORK_FILE = "artwork_history.json"
MAX_ARTWORK = 50
GUESTBOOK_FILE = "guestbook.json"
MAX_GUESTBOOK = 200
HOME_STATUS_FILE = "home_status.json"
ADMIN_PASSWORD = "live032319"
HEARTBEAT_TIMEOUT = 45  # seconds; draw session auto-expires if no message received
CHAT_RATE_LIMIT = 3.0  # seconds between chat messages per view connection
CHAT_FILE = "chat_history.json"
MAX_CHAT = 30
VISITORS_FILE = "visitors.json"
MAX_VISITORS = 50000

PROMPTS = [
    "a robot eating pizza",
    "a cat wearing a spacesuit",
    "a haunted house on a hill",
    "a dragon drinking coffee",
    "an underwater city",
    "a ghost riding a bicycle",
    "a wizard casting a spell",
    "a penguin at the beach",
    "a spaceship landing in a cornfield",
    "a bear fishing in a river",
    "a city made of candy",
    "a dog flying a kite",
    "a monster under the bed",
    "a mermaid playing guitar",
    "a volcano erupting confetti",
    "an astronaut playing chess",
    "a dinosaur at a birthday party",
    "a cloud with a face",
    "a submarine with windows",
    "a tree growing inside a house",
    "a fox reading a book",
    "a castle on a floating island",
    "a jellyfish in space",
    "a pirate map with an X",
    "a robot playing drums",
    "a bunny surfing a wave",
    "a lighthouse in a storm",
    "a frog on a lily pad",
    "a giant snail with a house shell",
    "a rocket launching from a backyard",
    "a knight fighting a dragon",
    "a snowy cabin in the woods",
    "a spider web at sunrise",
    "a whale jumping over the moon",
    "a cat dressed as Sherlock Holmes",
    "a hot air balloon over mountains",
    "a fish tank with tiny people inside",
    "a bicycle made of spaghetti",
    "the sun and moon having lunch",
    "a tiny elephant on a skateboard",
    "a flower growing from a volcano",
    "a bookshelf that goes to space",
    "a rain of lemons",
    "a crab playing a violin",
    "a hamster running a marathon",
    "a snowman in summer",
    "a robot gardening",
    "a magic door in a tree",
    "a duck driving a taxi",
    "a jar full of fireflies",
    "a wolf howling at a crescent moon",
    "a sloth winning a race",
    "a city in a snow globe",
    "a key that unlocks the sky",
    "an octopus writing a letter",
    "a panda eating ramen",
    "a haunted elevator",
    "a teapot pouring stars",
    "a dog wearing headphones",
    "a map of an imaginary island",
    "a butterfly made of stained glass",
    "a gingerbread house in summer",
    "a sleeping giant",
    "a caterpillar on a leaf",
    "a moon whose craters are swimming pools",
    "a robot barista",
    "a kite shaped like a dragon",
    "a pair of boots walking alone",
    "a magic wand making flowers grow",
    "a fox and a rabbit sharing an umbrella",
    "a brick wall covered in ivy",
    "a bicycle with wings",
    "a candy cane forest",
    "an astronaut playing soccer",
    "a turtle with a rocket on its shell",
    "a library inside a tree",
    "a bridge over a cloud",
    "an ice cream sundae the size of a car",
    "a cat on a throne",
    "a shipwreck at the bottom of the sea",
    "a bat flying past a full moon",
    "a goat riding a skateboard",
    "a clock melting",
    "a bird delivering a letter",
    "a dragon sleeping on a pile of pillows",
    "a shark in a business suit",
    "a door in the middle of the ocean",
    "a robot playing chess with a grandma",
    "a forest at night with glowing mushrooms",
    "a bear riding a unicycle",
    "a spaceship shaped like a teapot",
    "a city reflected in a puddle",
    "a dog building a sandcastle",
    "a moon-sized strawberry",
    "a cat in a top hat doing magic",
    "a bird's eye view of a maze",
    "an alien at a diner",
    "a monster brushing its teeth",
    "a snowflake under a magnifying glass",
    "a tiny house inside a seashell",
]


def get_daily_prompt() -> str:
    return PROMPTS[datetime.date.today().toordinal() % len(PROMPTS)]


app = FastAPI()
templates = Jinja2Templates(directory="templates")

_latest_frame: bytes | None = None
_geo_cache: dict[str, str] = {}
_presence: str = "home"  # "home" | "away" | "coding"
_last_location: str = ""
_last_visitor_time: float = 0.0
_artwork_editing: bool = False
_visitors: list[dict] = []
_visitor_ips: set[str] = set()


def _load_home_status() -> str:
    if os.path.exists(HOME_STATUS_FILE):
        try:
            with open(HOME_STATUS_FILE) as f:
                data = json.load(f)
                if "presence" in data:
                    return data["presence"]
                # backward compat: old {"home": true/false} format
                return "home" if data.get("home", True) else "away"
        except Exception:
            pass
    return "home"


def _save_home_status(presence: str):
    with open(HOME_STATUS_FILE, "w") as f:
        json.dump({"presence": presence}, f)


def _load_visitors() -> list:
    if os.path.exists(VISITORS_FILE):
        try:
            with open(VISITORS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_visitors():
    with open(VISITORS_FILE, "w") as f:
        json.dump(_visitors, f)


def _get_ws_ip(websocket: WebSocket) -> str:
    cf = websocket.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = websocket.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return websocket.client.host if websocket.client else ""


def _get_request_ip(request: Request) -> str:
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else ""


def _is_private(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return True


async def _lookup_geo(ip: str) -> str:
    global _visitors, _visitor_ips
    if ip in _geo_cache:
        return _geo_cache[ip]
    if not ip or _is_private(ip):
        _geo_cache[ip] = ""
        return ""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(
                f"http://ip-api.com/json/{ip}?fields=status,city,regionName,country,lat,lon"
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("status") == "success":
                    parts = [data.get("city", ""), data.get("regionName", ""), data.get("country", "")]
                    location = ", ".join(p for p in parts if p)
                    _geo_cache[ip] = location
                    if ip not in _visitor_ips and data.get("lat") is not None and data.get("lon") is not None:
                        _visitor_ips.add(ip)
                        entry = {
                            "lat": data["lat"],
                            "lon": data["lon"],
                            "city": data.get("city", ""),
                            "region": data.get("regionName", ""),
                            "country": data.get("country", ""),
                        }
                        _visitors.append(entry)
                        if len(_visitors) > MAX_VISITORS:
                            _visitors.pop(0)
                        _save_visitors()
                    return location
    except Exception:
        pass
    _geo_cache[ip] = ""
    return ""


def _load_chat() -> list:
    if os.path.exists(CHAT_FILE):
        try:
            with open(CHAT_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_chat(entries: list):
    with open(CHAT_FILE, "w") as f:
        json.dump(entries, f)


def _load_guestbook() -> list:
    if os.path.exists(GUESTBOOK_FILE):
        try:
            with open(GUESTBOOK_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_guestbook(entries: list):
    with open(GUESTBOOK_FILE, "w") as f:
        json.dump(entries, f)


def _load_artwork() -> list:
    if os.path.exists(ARTWORK_FILE):
        try:
            with open(ARTWORK_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_artwork(entries: list):
    with open(ARTWORK_FILE, "w") as f:
        json.dump(entries, f)


async def _record_view_location(ip: str):
    global _last_location
    loc = await _lookup_geo(ip)
    if loc:
        _last_location = loc


async def _poll_camera():
    global _latest_frame
    async with httpx.AsyncClient(timeout=2.0) as client:
        while True:
            try:
                r = await client.get(CAMERA_URL)
                if r.status_code == 200:
                    _latest_frame = r.content
            except Exception:
                pass
            await asyncio.sleep(POLL_INTERVAL)


@app.on_event("startup")
async def startup():
    global _presence, _visitors
    _presence = _load_home_status()
    _visitors = _load_visitors()
    manager.chat_history = _load_chat()
    asyncio.create_task(_poll_camera())
    asyncio.create_task(_moderation_loop())


class ConnectionManager:
    def __init__(self):
        self.draw_clients: list[WebSocket] = []
        self.display_clients: list[WebSocket] = []
        self.view_clients: list[WebSocket] = []
        self.history: list[dict] = []
        self._client_ips: dict[int, str] = {}  # id(websocket) → ip
        self.session_start: float | None = None
        self._view_last_reaction: dict[int, float] = {}  # id(websocket) → timestamp
        self._view_last_chat: dict[int, float] = {}  # id(websocket) → timestamp
        self.chat_history: list[dict] = []

    async def connect(self, websocket: WebSocket, role: str):
        await websocket.accept()
        if role == "draw":
            if not self.draw_clients:
                self.session_start = time.time()
            self.draw_clients.append(websocket)
            ip = _get_ws_ip(websocket)
            self._client_ips[id(websocket)] = ip
            asyncio.create_task(_lookup_geo(ip))
            if self.history:
                await websocket.send_text(
                    json.dumps({"type": "sync", "history": self.history})
                )
        elif role == "display":
            self.display_clients.append(websocket)
            await websocket.send_text(
                json.dumps({"type": "sync", "history": self.history})
            )
        elif role == "view":
            self.view_clients.append(websocket)
            self._view_last_reaction[id(websocket)] = 0
            self._view_last_chat[id(websocket)] = 0
            ip = _get_ws_ip(websocket)
            self._client_ips[id(websocket)] = ip
            asyncio.create_task(_record_view_location(ip))
            if self.chat_history:
                await websocket.send_text(
                    json.dumps({"type": "chat_history", "messages": self.chat_history})
                )

    def disconnect(self, websocket: WebSocket, role: str):
        if role == "draw" and websocket in self.draw_clients:
            self.draw_clients.remove(websocket)
            self._client_ips.pop(id(websocket), None)
            if not self.draw_clients:
                self.session_start = None
        elif role == "display" and websocket in self.display_clients:
            self.display_clients.remove(websocket)
        elif role == "view" and websocket in self.view_clients:
            self.view_clients.remove(websocket)
            self._client_ips.pop(id(websocket), None)
            self._view_last_reaction.pop(id(websocket), None)
            self._view_last_chat.pop(id(websocket), None)

    def update_history(self, message: dict):
        if message["type"] in ("stroke", "stamp", "fill"):
            self.history.append(message)

    async def end_session(self, websocket: WebSocket, name: str, duration: int, clear_display: bool = True, clear_history: bool = True):
        if not self.history:
            return
        strokes = list(self.history)
        ip = self._client_ips.get(id(websocket), "")
        location = await _lookup_geo(ip)

        entry = {
            "strokes": strokes,
            "name": name,
            "location": location,
            "time": time.time(),
            "duration": duration,
        }

        entries = _load_artwork()
        entries.append(entry)
        if len(entries) > MAX_ARTWORK:
            entries = entries[-MAX_ARTWORK:]
        _save_artwork(entries)
        asyncio.create_task(_check_artwork_moderation(entry["time"], _latest_frame))

        await self.broadcast_to_views({"type": "artwork_submitted"})
        if clear_history:
            self.history.clear()
        if clear_display:
            await self.broadcast_to_displays({"type": "clear"})

    async def broadcast_to_views(self, message: dict):
        dead = []
        for client in self.view_clients:
            try:
                await client.send_text(json.dumps(message))
            except Exception:
                dead.append(client)
        for client in dead:
            self.view_clients.remove(client)

    async def broadcast_to_all(self, message: dict):
        msg = json.dumps(message)
        for clients in (self.draw_clients, self.display_clients, self.view_clients):
            dead = []
            for client in clients:
                try:
                    await client.send_text(msg)
                except Exception:
                    dead.append(client)
            for client in dead:
                try:
                    clients.remove(client)
                except ValueError:
                    pass

    async def broadcast_to_displays(self, message: dict):
        dead = []
        for client in self.display_clients:
            try:
                await client.send_text(json.dumps(message))
            except Exception:
                dead.append(client)
        for client in dead:
            self.display_clients.remove(client)


manager = ConnectionManager()


@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    drawing = len(manager.draw_clients) > 0
    session_elapsed = (time.time() - manager.session_start) if manager.session_start is not None else None
    return templates.TemplateResponse("home.html", {"request": request, "presence": _presence, "drawing": drawing, "session_elapsed": session_elapsed, "last_location": _last_location})


@app.post("/set-home")
async def set_home():
    global _presence
    _presence = "home"
    _save_home_status("home")
    return JSONResponse({"presence": "home"})


@app.post("/set-away")
async def set_away():
    global _presence
    _presence = "away"
    _save_home_status("away")
    return JSONResponse({"presence": "away"})


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})


def _check_password(body: dict) -> bool:
    return body.get("password") == ADMIN_PASSWORD


@app.post("/admin/auth")
async def admin_auth(request: Request):
    body = await request.json()
    if not _check_password(body):
        return JSONResponse({"error": "wrong password"}, status_code=401)
    return JSONResponse({"ok": True})


@app.post("/admin/clear-guestbook")
async def admin_clear_guestbook(request: Request):
    body = await request.json()
    if not _check_password(body):
        return JSONResponse({"error": "wrong password"}, status_code=401)
    _save_guestbook([])
    return JSONResponse({"ok": True})


@app.post("/admin/clear-artwork")
async def admin_clear_artwork(request: Request):
    body = await request.json()
    if not _check_password(body):
        return JSONResponse({"error": "wrong password"}, status_code=401)
    _save_artwork([])
    return JSONResponse({"ok": True})


@app.post("/artwork/edit-start")
async def artwork_edit_start(request: Request):
    global _artwork_editing
    body = await request.json()
    if not _check_password(body):
        return JSONResponse({"error": "wrong password"}, status_code=401)
    _artwork_editing = True
    return JSONResponse({"ok": True})


@app.post("/artwork/edit-end")
async def artwork_edit_end(request: Request):
    global _artwork_editing
    body = await request.json()
    if not _check_password(body):
        return JSONResponse({"error": "wrong password"}, status_code=401)
    _artwork_editing = False
    return JSONResponse({"ok": True})


@app.post("/artwork/delete")
async def artwork_delete(request: Request):
    body = await request.json()
    if not _check_password(body):
        return JSONResponse({"error": "wrong password"}, status_code=401)
    ts = body.get("time")
    if ts is None:
        return JSONResponse({"error": "time required"}, status_code=400)
    entries = _load_artwork()
    new_entries = [e for e in entries if e.get("time") != ts]
    _save_artwork(new_entries)
    return JSONResponse({"ok": True, "deleted": len(entries) - len(new_entries)})


@app.post("/admin/set-home")
async def admin_set_home(request: Request):
    global _presence
    body = await request.json()
    if not _check_password(body):
        return JSONResponse({"error": "wrong password"}, status_code=401)
    _presence = "home"
    _save_home_status("home")
    return JSONResponse({"presence": "home"})


@app.post("/admin/set-away")
async def admin_set_away(request: Request):
    global _presence
    body = await request.json()
    if not _check_password(body):
        return JSONResponse({"error": "wrong password"}, status_code=401)
    _presence = "away"
    _save_home_status("away")
    return JSONResponse({"presence": "away"})


@app.post("/admin/set-coding")
async def admin_set_coding(request: Request):
    global _presence
    body = await request.json()
    if not _check_password(body):
        return JSONResponse({"error": "wrong password"}, status_code=401)
    _presence = "coding"
    _save_home_status("coding")
    return JSONResponse({"presence": "coding"})


CAMERA_CONTROL_URL = "http://10.0.0.8:8080/controls"
NTFY_GUESTBOOK_TOPIC = "livedoodle-guestbook-submission"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
MODERATION_LOG_FILE = "moderation_log.json"


async def _notify_ntfy(message: str, topic: str, title: str):
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"https://ntfy.sh/{topic}",
                content=message.encode(),
                headers={"Title": title},
            )
    except Exception:
        pass


async def _moderate_frame(frame: bytes) -> tuple[bool, str]:
    b64 = base64.b64encode(frame).decode()
    prompt = (
        "You are a content moderator for a public drawing app. "
        "Look at this image and determine if it contains nudity, hate symbols, "
        "racial slurs, graphic violence, or racist imagery. "
        "Only flag clear and obvious violations — ignore ambiguous sketches. "
        'Respond with JSON only, no other text: {"flagged": true/false, "reason": "brief reason if flagged, else empty string"}'
    )
    payload = {
        "model": "llama-3.2-11b-vision-preview",
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": prompt},
        ]}],
        "max_tokens": 100,
        "temperature": 0,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        result = json.loads(content)
        return bool(result.get("flagged")), str(result.get("reason", ""))


def _log_moderation(ip: str, reason: str, session_duration: int):
    entry = {"ip": ip, "reason": reason, "timestamp": time.time(), "session_duration": session_duration}
    log = []
    if os.path.exists(MODERATION_LOG_FILE):
        try:
            with open(MODERATION_LOG_FILE) as f:
                log = json.load(f)
        except Exception:
            pass
    log.append(entry)
    with open(MODERATION_LOG_FILE, "w") as f:
        json.dump(log, f)


async def _check_artwork_moderation(entry_time: float, frame: bytes):
    if not GROQ_API_KEY or not frame:
        return
    try:
        flagged, reason = await _moderate_frame(frame)
        if flagged:
            entries = _load_artwork()
            new_entries = [e for e in entries if e.get("time") != entry_time]
            if len(new_entries) < len(entries):
                _save_artwork(new_entries)
                print(f"[moderation] Deleted artwork {entry_time}: {reason}")
    except Exception as e:
        print(f"[moderation] Post-submit check error: {e}")


async def _moderation_loop():
    while True:
        await asyncio.sleep(60)
        if not manager.draw_clients or _latest_frame is None or not GROQ_API_KEY:
            continue
        try:
            flagged, reason = await _moderate_frame(_latest_frame)
            if flagged:
                session_dur = int(time.time() - manager.session_start) if manager.session_start else 0
                ip = manager._client_ips.get(id(manager.draw_clients[0]), "") if manager.draw_clients else ""
                _log_moderation(ip, reason, session_dur)
                manager.history.clear()
                await manager.broadcast_to_displays({"type": "clear"})
                await manager.broadcast_to_all({"type": "whoops", "reason": reason})
                for ws in list(manager.draw_clients):
                    try:
                        await ws.close()
                    except Exception:
                        pass
        except Exception as e:
            print(f"[moderation] Loop error: {e}")


@app.post("/admin/camera-control")
async def admin_camera_control(request: Request):
    body = await request.json()
    if not _check_password(body):
        return JSONResponse({"error": "wrong password"}, status_code=401)
    controls = {k: v for k, v in body.items() if k != "password"}
    if not controls:
        return JSONResponse({"error": "no controls"}, status_code=400)
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.post(
                CAMERA_CONTROL_URL,
                content=json.dumps(controls),
                headers={"Content-Type": "application/json"},
            )
            return JSONResponse({"ok": r.status_code == 200, "status": r.status_code})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@app.post("/admin/reload-display")
async def admin_reload_display(request: Request):
    body = await request.json()
    if not _check_password(body):
        return JSONResponse({"error": "wrong password"}, status_code=401)
    await manager.broadcast_to_displays({"type": "reload"})
    return JSONResponse({"ok": True})


@app.get("/draw", response_class=HTMLResponse)
async def draw_page(request: Request):
    return templates.TemplateResponse("draw.html", {"request": request, "prompt": get_daily_prompt()})


@app.get("/display", response_class=HTMLResponse)
async def display_page(request: Request):
    return templates.TemplateResponse("display.html", {"request": request})


@app.get("/status")
async def status():
    global _last_visitor_time
    _last_visitor_time = time.time()
    drawing = len(manager.draw_clients) > 0
    elapsed = (time.time() - manager.session_start) if manager.session_start is not None else None
    viewers = len(manager.view_clients) + len(manager.draw_clients)
    return JSONResponse({"drawing": drawing, "session_elapsed": elapsed, "viewers": viewers, "last_location": _last_location, "artwork_editing": _artwork_editing})


@app.get("/snapshot")
async def snapshot():
    if _latest_frame is None:
        return Response(status_code=503)
    return Response(content=_latest_frame, media_type="image/jpeg")


async def _mjpeg_generator():
    while True:
        if _latest_frame:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + _latest_frame
                + b"\r\n"
            )
        await asyncio.sleep(POLL_INTERVAL)


@app.get("/stream")
async def stream():
    return StreamingResponse(
        _mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/og-image.png")
async def og_image():
    if not os.path.exists("og-image.png"):
        return Response(status_code=404)
    with open("og-image.png", "rb") as f:
        return Response(content=f.read(), media_type="image/png")


@app.get("/artwork", response_class=HTMLResponse)
async def artwork_page(request: Request):
    return templates.TemplateResponse("artwork.html", {"request": request})


@app.get("/artwork/entries")
async def artwork_entries():
    return JSONResponse(_load_artwork())


@app.get("/donate", response_class=HTMLResponse)
async def donate_page(request: Request):
    return templates.TemplateResponse("donate.html", {"request": request})


@app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    return templates.TemplateResponse("about.html", {"request": request})


@app.get("/heatmap", response_class=HTMLResponse)
async def heatmap_page(request: Request):
    return templates.TemplateResponse("heatmap.html", {"request": request})


@app.get("/visitors")
async def visitors_data():
    return JSONResponse(_visitors)


@app.get("/guestbook", response_class=HTMLResponse)
async def guestbook_page(request: Request):
    return templates.TemplateResponse("guestbook.html", {"request": request})


@app.get("/guestbook/entries")
async def guestbook_entries():
    return JSONResponse(_load_guestbook())


@app.post("/guestbook/sign")
async def guestbook_sign(request: Request):
    body = await request.json()
    name = str(body.get("name", "")).strip()[:50] or "Anonymous"
    message = str(body.get("message", "")).strip()[:280]
    if not message:
        return JSONResponse({"error": "message required"}, status_code=400)
    ip = _get_request_ip(request)
    location = await _lookup_geo(ip)
    entry = {"name": name, "message": message, "location": location, "time": time.time(), "likes": 0}
    entries = _load_guestbook()
    entries.append(entry)
    if len(entries) > MAX_GUESTBOOK:
        entries = entries[-MAX_GUESTBOOK:]
    _save_guestbook(entries)
    loc_str = f" from {location}" if location else ""
    asyncio.create_task(_notify_ntfy(
        f"{name}{loc_str}: {message[:100]}",
        NTFY_GUESTBOOK_TOPIC,
        "New guestbook entry",
    ))
    return JSONResponse({"ok": True})


@app.post("/guestbook/like")
async def guestbook_like(request: Request):
    body = await request.json()
    ts = body.get("time")
    if ts is None:
        return JSONResponse({"error": "time required"}, status_code=400)
    entries = _load_guestbook()
    for e in entries:
        if e.get("time") == ts:
            e["likes"] = e.get("likes", 0) + 1
            _save_guestbook(entries)
            return JSONResponse({"ok": True, "likes": e["likes"]})
    return JSONResponse({"error": "not found"}, status_code=404)


@app.get("/activity")
async def activity():
    return JSONResponse({"last_visitor_time": _last_visitor_time})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, role: str = "draw"):
    global _last_visitor_time
    if role == "draw" and manager.draw_clients:
        await websocket.accept()
        await websocket.send_text(json.dumps({"type": "busy"}))
        await websocket.close()
        return
    await manager.connect(websocket, role)
    if role == "draw":
        _last_visitor_time = time.time()
    try:
        while True:
            try:
                if role == "draw":
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=HEARTBEAT_TIMEOUT)
                else:
                    data = await websocket.receive_text()
            except asyncio.TimeoutError:
                break
            message = json.loads(data)
            if role == "draw":
                if message["type"] == "heartbeat":
                    _last_visitor_time = time.time()
                elif message["type"] in ("stroke", "stamp", "fill"):
                    if not manager.history:
                        await manager.broadcast_to_displays({"type": "clear"})
                    manager.update_history(message)
                    await manager.broadcast_to_displays(message)
                elif message["type"] == "finish":
                    name = str(message.get("name", "Anonymous")).strip() or "Anonymous"
                    duration = int(message.get("duration", 0))
                    await manager.end_session(websocket, name, duration, clear_display=False, clear_history=False)
                elif message["type"] == "redraw":
                    manager.history = [m for m in message.get("history", []) if m.get("type") in ("stroke", "stamp", "fill")]
                    await manager.broadcast_to_displays({"type": "sync", "history": manager.history})
                elif message["type"] == "clear":
                    name = str(message.get("name", "Anonymous")).strip() or "Anonymous"
                    duration = int(message.get("duration", 0))
                    await manager.end_session(websocket, name, duration, clear_display=True)
                elif message["type"] == "wipe":
                    manager.history.clear()
                    await manager.broadcast_to_displays({"type": "clear"})
            elif role == "view":
                if message.get("type") == "reaction":
                    emoji = message.get("emoji", "")
                    if emoji in {"❤️", "🔥", "👏", "🤯", "👀", "✨", "😂"}:
                        now = time.time()
                        if now - manager._view_last_reaction.get(id(websocket), 0) >= 0.3:
                            manager._view_last_reaction[id(websocket)] = now
                            await manager.broadcast_to_displays({"type": "reaction", "emoji": emoji})
                elif message.get("type") == "chat":
                    text = str(message.get("text", "")).strip()[:200]
                    if text:
                        now = time.time()
                        if now - manager._view_last_chat.get(id(websocket), 0) >= CHAT_RATE_LIMIT:
                            manager._view_last_chat[id(websocket)] = now
                            ip = manager._client_ips.get(id(websocket), "")
                            location = _geo_cache.get(ip, "").strip()
                            from_label = location.upper() if location else "VISITOR"
                            msg = {"type": "chat", "text": text, "from": from_label, "time": now}
                            manager.chat_history.append(msg)
                            if len(manager.chat_history) > MAX_CHAT:
                                manager.chat_history = manager.chat_history[-MAX_CHAT:]
                            _save_chat(manager.chat_history)
                            await manager.broadcast_to_views(msg)
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket, role)
