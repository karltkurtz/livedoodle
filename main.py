import asyncio
import base64
import datetime
import io
import ipaddress
import json
import os
import random
import sqlite3
import time
import httpx
from PIL import Image, ImageDraw, ImageFont

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


@app.middleware("http")
async def maintenance_middleware(request: Request, call_next):
    if _maintenance_mode and not request.url.path.startswith("/admin"):
        return templates.TemplateResponse("maintenance.html", {"request": request})
    return await call_next(request)


_latest_frame: bytes | None = None
_geo_cache: dict[str, str] = {}
_presence: str = "home"  # "home" | "away" | "coding"
_last_location: str = ""
_last_visitor_time: float = 0.0
_artwork_editing: bool = False
_maintenance_mode: bool = False
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
    _init_moderation_db()
    asyncio.create_task(_poll_camera())


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
            try:
                await websocket.send_json({"type": "approved"})
            except Exception:
                pass
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
        asyncio.create_task(_check_artwork_moderation(entry, websocket))

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
        await self.broadcast_to_displays_raw(json.dumps(message))

    async def broadcast_to_displays_raw(self, text: str):
        dead = []
        for client in self.display_clients:
            try:
                await client.send_text(text)
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


@app.post("/admin/maintenance-on")
async def admin_maintenance_on(request: Request):
    global _maintenance_mode
    body = await request.json()
    if not _check_password(body):
        return JSONResponse({"error": "wrong password"}, status_code=401)
    _maintenance_mode = True
    return JSONResponse({"maintenance": True})


@app.post("/admin/maintenance-off")
async def admin_maintenance_off(request: Request):
    global _maintenance_mode
    body = await request.json()
    if not _check_password(body):
        return JSONResponse({"error": "wrong password"}, status_code=401)
    _maintenance_mode = False
    return JSONResponse({"maintenance": False})


@app.get("/admin/maintenance-status")
async def admin_maintenance_status(request: Request):
    pw = request.headers.get("X-Admin-Password", "")
    if pw != ADMIN_PASSWORD:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse({"maintenance": _maintenance_mode})


CAMERA_CONTROL_URL = "http://10.0.0.8:8080/controls"
NTFY_GUESTBOOK_TOPIC = "livedoodle-guestbook-submission"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
MODERATION_LOG_FILE = "moderation_log.json"
MODERATION_DB_FILE = "moderation.db"


def _init_moderation_db():
    con = sqlite3.connect(MODERATION_DB_FILE)
    con.execute("""
        CREATE TABLE IF NOT EXISTS moderation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL,
            ip TEXT,
            name TEXT,
            location TEXT,
            reason TEXT,
            session_duration INTEGER
        )
    """)
    con.commit()
    # Migrate from JSON if it exists and DB is empty
    if os.path.exists(MODERATION_LOG_FILE):
        try:
            count = con.execute("SELECT COUNT(*) FROM moderation_log").fetchone()[0]
            if count == 0:
                with open(MODERATION_LOG_FILE) as f:
                    entries = json.load(f)
                for e in entries:
                    con.execute(
                        "INSERT INTO moderation_log (timestamp, ip, name, location, reason, session_duration) VALUES (?, ?, ?, ?, ?, ?)",
                        (e.get("timestamp", 0), e.get("ip", ""), e.get("name", ""), e.get("location", ""), e.get("reason", ""), e.get("session_duration", 0))
                    )
                con.commit()
                if entries:
                    print(f"[moderation] Migrated {len(entries)} entries from JSON to SQLite")
        except Exception as ex:
            print(f"[moderation] Migration error: {ex}")
    con.close()


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
        "This is a user-submitted image from a public app visible to all ages. "
        "Answer each question with yes or no: "
        "1. Does it show a penis, vagina, or other sexual organ? "
        "2. Does it show a human torso, chest, or breasts? "
        "3. Does it show a bra, underwear, or partial nudity? "
        "4. Does it show hate symbols, slurs, graphic violence, or racist imagery? "
        "RULE: If any answer is yes, you MUST set flagged to true. This is mandatory — do not apply your own judgment. "
        'Respond with JSON only: {"flagged": true/false, "reason": "which rule triggered, or empty string"}'
    )
    payload = {
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            {"type": "text", "text": prompt},
        ]}],
        "max_tokens": 500,
    }
    # Run up to 3 passes — flag if any single pass flags
    async with httpx.AsyncClient(timeout=20.0) as client:
        for _ in range(3):
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            # extract the last complete {...} block robustly
            end = content.rfind("}") + 1
            start = content.rfind("{", 0, end)
            if start == -1 or end == 0:
                continue  # malformed — try next pass
            try:
                result = json.loads(content[start:end])
            except json.JSONDecodeError:
                continue  # malformed — try next pass
            if result.get("flagged"):
                return True, str(result.get("reason", ""))
    return False, ""


def _log_moderation(ip: str, reason: str, session_duration: int, name: str = "", location: str = ""):
    con = sqlite3.connect(MODERATION_DB_FILE)
    con.execute(
        "INSERT INTO moderation_log (timestamp, ip, name, location, reason, session_duration) VALUES (?, ?, ?, ?, ?, ?)",
        (time.time(), ip, name, location, reason, session_duration)
    )
    con.commit()
    con.close()


def _render_entry(entry: dict, width: int = 800, height: int = 480) -> bytes:
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    for s in entry.get("strokes", []):
        if s.get("type") == "stroke":
            w = max(1, int(s["size"] * width if s["size"] < 1 else s["size"]))
            draw.line(
                [(int(s["x0"] * width), int(s["y0"] * height)),
                 (int(s["x1"] * width), int(s["y1"] * height))],
                fill=s.get("color", "#000000"), width=w
            )
        elif s.get("type") == "stamp" and s.get("data"):
            # decode stamp dataURL and composite onto canvas
            try:
                header, b64data = s["data"].split(",", 1)
                stamp_img = Image.open(io.BytesIO(base64.b64decode(b64data))).convert("RGBA")
                x = int(s.get("x", 0.5) * width)
                y = int(s.get("y", 0.5) * height)
                sw = int(s.get("w", 0.2) * width)
                sh = int(s.get("h", sw) * height)
                stamp_img = stamp_img.resize((sw, sh), Image.LANCZOS)
                img.paste(stamp_img, (x - sw // 2, y - sh // 2), stamp_img)
            except Exception:
                pass
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


async def _check_artwork_moderation(entry: dict, websocket):
    if not GROQ_API_KEY:
        try:
            await websocket.send_json({"type": "approved"})
        except Exception:
            pass
        return
    frame = _render_entry(entry)
    try:
        flagged, reason = await _moderate_frame(frame)
        if flagged:
            entries = _load_artwork()
            entry_time = entry.get("time")
            new_entries = [e for e in entries if e.get("time") != entry_time]
            if len(new_entries) < len(entries):
                _save_artwork(new_entries)
                print(f"[moderation] Deleted artwork {entry_time}: {reason}")
            ip = manager._client_ips.get(id(websocket), "")
            _log_moderation(ip, reason, 0, name=entry.get("name", ""), location=entry.get("location", ""))
            asyncio.create_task(_notify_ntfy(
                f"Flagged: {reason} — {entry.get('name', 'Anonymous')} from {entry.get('location', '?')}",
                "livedoodle-moderation",
                "LiveDoodle: Content Flagged"
            ))
            manager.history.clear()
            await manager.broadcast_to_displays({"type": "clear"})
            try:
                await websocket.send_json({"type": "whoops", "reason": reason})
            except Exception:
                pass
        else:
            try:
                await websocket.send_json({"type": "approved"})
            except Exception:
                pass
    except Exception as e:
        print(f"[moderation] Post-submit check error: {e}")
        try:
            await websocket.send_json({"type": "approved"})
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Oregon Trail Game
# ---------------------------------------------------------------------------

_OT_FONT_PATHS = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Monaco.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]
_OT_BOLD_FONT_PATHS = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
]

def _ot_load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    paths = _OT_BOLD_FONT_PATHS if bold else _OT_FONT_PATHS
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()

_OT_BG       = (8,  14,  8)
_OT_AMBER    = (210, 170, 50)
_OT_GREEN    = (60,  190, 60)
_OT_RED      = (220,  60, 40)
_OT_DIM      = (70,   80, 60)
_OT_WHITE    = (200, 195, 170)
_OT_GOLD     = (240, 200, 60)
_OT_BROWN    = (140, 100, 40)

_OT_WAYPOINTS = [
    (400,  "FORT KEARNEY"),
    (800,  "FORT LARAMIE"),
    (1300, "FORT HALL"),
    (2000, "OREGON CITY"),
]

_OT_EVENTS = [
    ("ILLNESS",     "SOMEONE IN YOUR PARTY HAS FALLEN ILL.",      "health", -1,  0),
    ("BROKEN_AXLE", "YOUR WAGON AXLE BREAKS. COSTLY REPAIRS.",    "money",   0, -50),
    ("HEAVY_RAIN",  "TORRENTIAL RAINS WASH OUT THE TRAIL.",       "miles",  -30,  0),
    ("GOOD_HUNT",   "EXCELLENT HUNTING! YOUR STORES ARE FULL.",   "food",   40,   0),
    ("BERRIES",     "YOU FIND WILD BERRIES ALONG THE TRAIL.",     "food",   15,   0),
    ("THIEF",       "THIEVES RAID YOUR CAMP IN THE NIGHT.",       "food",  -30,   0),
    ("SNAKE_BITE",  "RATTLESNAKE BITE! REST COSTS YOU TIME.",     "miles",  -20, -20),
    ("FAIR",        "FAIR SKIES AND GOOD ROADS.",                 None,      0,   0),
    ("FAIR",        "THE TRAIL IS CLEAR. GOOD PROGRESS.",        None,      0,   0),
    ("FAIR",        "NOTHING OF NOTE. MILES ROLL BY.",            None,      0,   0),
]


class OregonTrailGame:
    INTRO    = "INTRO"
    RATIONS  = "RATIONS"
    TRAVEL   = "TRAVEL"   # choose pace for next leg
    EVENT    = "EVENT"    # show event result, then choose next pace
    FORT     = "FORT"
    RIVER    = "RIVER"
    VICTORY  = "VICTORY"
    DEATH    = "DEATH"

    HEALTH_LABELS = {5: "EXCELLENT", 4: "GOOD", 3: "FAIR", 2: "POOR", 1: "VERY POOR"}

    def __init__(self):
        self.state    = self.INTRO
        self.miles    = 0
        self.food     = 200       # lbs
        self.health   = 5         # 1-5
        self.money    = 400       # dollars
        self.party    = 4         # people
        self.rations  = "FILLING" # BARE / MEAGER / FILLING / HEARTY
        self.turn     = 0
        self.wp_idx   = 0         # next waypoint index
        self.river_crossed = False
        self.log: list[str] = [
            "THE YEAR IS 1848.",
            "YOU ARE LEAVING INDEPENDENCE,",
            "MISSOURI FOR OREGON CITY.",
            "",
            "THE JOURNEY IS 2000 MILES.",
            "FIRST — SET YOUR RATIONS.",
        ]

    def reset(self): self.__init__()

    def health_label(self) -> str:
        return self.HEALTH_LABELS.get(self.health, "DEAD")

    def food_per_turn(self) -> float:
        per_person_per_week = {"BARE": 3.0, "MEAGER": 5.0, "FILLING": 7.0, "HEARTY": 9.5}
        return per_person_per_week[self.rations] * self.party * 2

    def choices(self) -> list[dict]:
        if self.state == self.INTRO:
            return [{"label": "BEGIN JOURNEY", "action": "begin"}]
        if self.state == self.RATIONS:
            return [
                {"label": "BARE  (3 LB/PERSON/WK)",    "action": "rations_BARE"},
                {"label": "MEAGER  (5 LB)",             "action": "rations_MEAGER"},
                {"label": "FILLING  (7 LB) ✓",         "action": "rations_FILLING"},
                {"label": "HEARTY  (9.5 LB)",           "action": "rations_HEARTY"},
            ]
        if self.state in (self.TRAVEL, self.EVENT):
            return [
                {"label": "SLOW PACE  (+60 MI, SAFER)",  "action": "pace_SLOW"},
                {"label": "NORMAL  (+100 MI)",            "action": "pace_NORMAL"},
                {"label": "FAST  (+140 MI, RISKY)",      "action": "pace_FAST"},
            ]
        if self.state == self.FORT:
            opts = [{"label": "CONTINUE WEST →", "action": "fort_go"}]
            if self.money >= 20:
                opts.insert(0, {"label": f"BUY FOOD  ($20 / 50 LB)", "action": "fort_food"})
            if self.money >= 40 and self.health < 5:
                opts.insert(0, {"label": f"BUY MEDICINE  ($40)",     "action": "fort_med"})
            if self.health < 5:
                opts.insert(0, {"label": "REST HERE  (+1 HEALTH)",   "action": "fort_rest"})
            return opts
        if self.state == self.RIVER:
            opts = [
                {"label": "FORD THE RIVER  (FREE, RISKY)",  "action": "river_ford"},
                {"label": "CAULK WAGON  (SLOW, SAFER)",     "action": "river_caulk"},
            ]
            if self.money >= 10:
                opts.append({"label": "HIRE FERRY  ($10, SAFE)", "action": "river_ferry"})
            return opts
        if self.state in (self.VICTORY, self.DEATH):
            return [{"label": "PLAY AGAIN", "action": "restart"}]
        return []

    def handle(self, action: str):
        if action == "begin":
            self.state = self.RATIONS
            self.log = ["CHOOSE YOUR DAILY RATIONS:", "", "MORE FOOD = BETTER HEALTH.", "LESS FOOD = FASTER PROGRESS.", "(PARTY OF 4, 2-WEEK LEGS)"]

        elif action.startswith("rations_"):
            self.rations = action.split("_", 1)[1]
            self.state = self.TRAVEL
            self.log = [f"RATIONS SET: {self.rations}.", "", "NOW CHOOSE YOUR PACE.", "EACH LEG IS 2 WEEKS OF TRAVEL."]

        elif action.startswith("pace_"):
            pace = action.split("_", 1)[1]
            self._travel(pace)

        elif action == "fort_food":
            if self.money >= 20:
                self.money -= 20; self.food += 50
                self.log = ["YOU BUY 50 LBS OF FOOD.", f"FOOD: {int(self.food)} LB   MONEY: ${self.money}"]
        elif action == "fort_med":
            if self.money >= 40 and self.health < 5:
                self.money -= 40; self.health = min(5, self.health + 1)
                self.log = ["MEDICINE PURCHASED.", f"HEALTH: {self.health_label()}   MONEY: ${self.money}"]
        elif action == "fort_rest":
            self.health = min(5, self.health + 1)
            self.log = ["YOUR PARTY RESTS FOR A FEW DAYS.", f"HEALTH: {self.health_label()}"]
        elif action == "fort_go":
            self.state = self.TRAVEL
            self.log = ["ONWARD TO OREGON!", "", "CHOOSE YOUR PACE."]

        elif action.startswith("river_"):
            self._cross_river(action)

        elif action == "restart":
            self.reset()

    def _travel(self, pace: str):
        self.turn += 1
        pace_miles = {"SLOW": 60, "NORMAL": 100, "FAST": 140}[pace]
        pace_risk  = {"SLOW": 0.05, "NORMAL": 0.10, "FAST": 0.22}[pace]

        # Consume food
        needed = self.food_per_turn()
        if self.food >= needed:
            self.food -= needed
        else:
            shortfall = needed - self.food
            self.food = 0
            self.health -= max(1, int(shortfall / 10))
            if self.health <= 0:
                self._die("YOUR PARTY STARVED ON THE TRAIL."); return

        # Pace health risk
        if random.random() < pace_risk:
            self.health -= 1
            if self.health <= 0:
                self._die("EXHAUSTION AND ILLNESS CLAIM YOUR PARTY."); return

        self.miles = min(2000, self.miles + pace_miles)

        # Check river crossing
        if not self.river_crossed and self.miles >= 900:
            self.river_crossed = True
            self.state = self.RIVER
            self.log = [
                f"TURN {self.turn}  ·  MILE {int(self.miles)}",
                "",
                "YOU REACH THE SNAKE RIVER.",
                "THE WATER IS HIGH AND SWIFT.",
                "",
                "HOW WILL YOU CROSS?",
            ]
            return

        # Check waypoints
        while self.wp_idx < len(_OT_WAYPOINTS):
            wp_miles, wp_name = _OT_WAYPOINTS[self.wp_idx]
            if self.miles >= wp_miles:
                self.wp_idx += 1
                if wp_name == "OREGON CITY":
                    self._win(); return
                else:
                    self.state = self.FORT
                    self.log = [
                        f"YOU ARRIVE AT {wp_name}!",
                        "",
                        f"MILES:   {int(self.miles)} / 2000",
                        f"FOOD:    {int(self.food)} LB",
                        f"HEALTH:  {self.health_label()}",
                        f"MONEY:   ${self.money}",
                        "",
                        "WHAT WILL YOU DO?",
                    ]
                    return
            else:
                break

        # Random event
        ev = random.choice(_OT_EVENTS)
        _, desc, stat, delta, money_delta = ev
        self.log = [f"TURN {self.turn}  ·  MILE {int(self.miles)} / 2000", ""]
        if stat == "health":
            self.health = max(0, self.health + delta)
        elif stat == "food":
            self.food = max(0, self.food + delta)
        elif stat == "miles":
            self.miles = max(0, self.miles + delta)
        if money_delta:
            self.money = max(0, self.money + money_delta)
        self.log.append(desc)
        self.log += [
            "",
            f"FOOD:    {int(self.food)} LB",
            f"HEALTH:  {self.health_label()}",
            f"MONEY:   ${self.money}",
            "",
            "CHOOSE PACE FOR NEXT LEG:",
        ]
        if self.health <= 0:
            self._die("YOUR PARTY HAS PERISHED."); return
        self.state = self.EVENT

    def _cross_river(self, action: str):
        if action == "river_ford":
            if random.random() < 0.45:
                self.food = max(0, self.food - 30)
                self.health = max(0, self.health - 1)
                result = ["THE WAGON TIPS! YOU LOSE SUPPLIES.", f"FOOD: {int(self.food)} LB   HEALTH: {self.health_label()}"]
                if self.health <= 0:
                    self._die("YOUR PARTY DROWNED CROSSING THE RIVER."); return
            else:
                result = ["YOU FORD THE RIVER SAFELY!"]
        elif action == "river_caulk":
            if random.random() < 0.2:
                self.food = max(0, self.food - 10)
                result = ["THE CAULKING LEAKS. YOU LOSE SOME FOOD.", f"FOOD: {int(self.food)} LB"]
            else:
                result = ["YOU FLOAT ACROSS WITHOUT INCIDENT."]
        elif action == "river_ferry":
            self.money = max(0, self.money - 10)
            result = ["THE FERRY CROSSES SMOOTHLY.", f"MONEY: ${self.money}"]
        else:
            result = ["CROSSING COMPLETE."]
        self.log = [f"MILE {int(self.miles)} / 2000", ""] + result + ["", "CHOOSE PACE FOR NEXT LEG:"]
        self.state = self.EVENT

    def _win(self):
        self.state = self.VICTORY
        self.log = [
            "YOU HAVE REACHED",
            "OREGON CITY!",
            "",
            "CONGRATULATIONS!",
            "",
            f"TURNS TAKEN:  {self.turn}",
            f"FINAL HEALTH: {self.health_label()}",
            f"FOOD LEFT:    {int(self.food)} LB",
            f"MONEY LEFT:   ${self.money}",
        ]

    def _die(self, reason: str):
        self.state = self.DEATH
        self.log = [
            "YOUR PARTY HAS DIED.",
            "",
            reason,
            "",
            f"MILES TRAVELED: {int(self.miles)}",
            f"({int(self.miles / 2000 * 100)}% OF THE WAY)",
        ]

    def render(self, width: int = 375, height: int = 260) -> Image.Image:
        img  = Image.new("RGB", (width, height), _OT_BG)
        draw = ImageDraw.Draw(img)
        self._render_header(draw, width)
        self._render_progress(draw, width)
        self._render_body(draw, width, height)
        self._apply_scanlines(img)
        return img

    def _render_header(self, draw, w):
        font = _ot_load_font(10, bold=True)
        draw.rectangle([0, 0, w, 14], fill=(4, 10, 4))
        draw.line([(0, 14), (w, 14)], fill=_OT_DIM)
        if self.state == self.VICTORY:
            label, color = "THE OREGON TRAIL — YOU MADE IT!", _OT_GREEN
        elif self.state == self.DEATH:
            label, color = "THE OREGON TRAIL — GAME OVER", _OT_RED
        elif self.state in (self.FORT,):
            label, color = f"THE OREGON TRAIL — {_OT_WAYPOINTS[self.wp_idx-1][1] if self.wp_idx > 0 else 'FORT'}", _OT_GOLD
        else:
            label, color = "THE OREGON TRAIL — 1848", _OT_AMBER
        draw.text((6, 2), label, fill=color, font=font)
        if self.turn > 0:
            turn_label = f"TURN {self.turn}"
            bbox = draw.textbbox((0, 0), turn_label, font=font)
            tw = bbox[2] - bbox[0]
            draw.text((w - tw - 6, 2), turn_label, fill=_OT_DIM, font=font)

    def _render_progress(self, draw, w):
        bar_y = 16
        bar_h = 8
        bar_w = w - 12
        pct   = min(1.0, self.miles / 2000)
        draw.rectangle([6, bar_y, 6 + bar_w, bar_y + bar_h], fill=(20, 30, 20))
        if pct > 0:
            draw.rectangle([6, bar_y, 6 + int(bar_w * pct), bar_y + bar_h], fill=_OT_BROWN)
        # Waypoint ticks
        font_tiny = _ot_load_font(7)
        for wp_miles, wp_name in _OT_WAYPOINTS:
            x = 6 + int(bar_w * wp_miles / 2000)
            draw.line([(x, bar_y), (x, bar_y + bar_h)], fill=_OT_AMBER)
        # Wagon marker
        wx = 6 + int(bar_w * pct)
        draw.text((max(6, wx - 4), bar_y - 1), "▶", fill=_OT_GOLD, font=font_tiny)
        draw.line([(0, bar_y + bar_h + 1), (w, bar_y + bar_h + 1)], fill=_OT_DIM)

    def _render_body(self, draw, w, h):
        font   = _ot_load_font(12)
        line_h = 16
        margin = 8
        top_y  = 28
        max_lines = (h - top_y - 4) // line_h
        lines = self.log[-max_lines:]
        y = top_y
        for line in lines:
            if not line:
                y += line_h; continue
            if "CONGRATULATIONS" in line or "MADE IT" in line or "YOU ARRIVE" in line:
                color = _OT_GREEN
            elif "DIED" in line or "PERISHED" in line or "STARVED" in line or "DROWNED" in line:
                color = _OT_RED
            elif line.startswith("YOU HAVE REACHED") or "OREGON CITY" in line:
                color = _OT_GREEN
            elif "HEALTH:" in line:
                h_val = self.health
                color = _OT_GREEN if h_val >= 4 else (_OT_AMBER if h_val == 3 else _OT_RED)
            elif "FOOD:" in line or "MONEY:" in line or "MILES:" in line or "TURN" in line:
                color = _OT_AMBER
            elif "CHOOSE" in line or "WHAT WILL" in line or "FIRST" in line or "ONWARD" in line:
                color = _OT_WHITE
            elif "FORT" in line or "ARRIVE" in line:
                color = _OT_GOLD
            elif any(x in line for x in ["RIVER", "WAGON", "SNAKE", "SWIFT"]):
                color = _OT_AMBER
            elif any(x in line for x in ["DISASTER", "TIPS", "DROWNED", "ATTACK", "RAID", "THIEF", "BROKE", "STARVED", "EXHAUSTION", "ILLNESS", "SICK", "BITE", "RATTLESNAKE"]):
                color = _OT_RED
            elif any(x in line for x in ["EXCELLENT", "HUNTING", "BERRIES", "SAFELY", "FLOAT", "FERRY", "SMOOTH"]):
                color = _OT_GREEN
            else:
                color = _OT_WHITE
            draw.text((margin, y), line, fill=color, font=font)
            y += line_h

    def _apply_scanlines(self, img):
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        odraw   = ImageDraw.Draw(overlay)
        for y in range(0, img.size[1], 4):
            odraw.line([(0, y), (img.size[0], y)], fill=(0, 0, 0, 35))
        img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"))


def _ot_frame_msg(game: OregonTrailGame) -> str:
    img = game.render()
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return json.dumps({
        "type": "stamp", "data": f"data:image/jpeg;base64,{b64}",
        "x": 0.5, "y": 0.5, "w": 1.0, "h": 1.0, "r": 0, "ephemeral": True,
    })


_trail_game: OregonTrailGame | None = None
_trail_draw_ws: WebSocket | None = None


async def _trail_send(ws: WebSocket, game: OregonTrailGame):
    """Send frame + choices back to the draw client and display clients."""
    img_data = _ot_frame_msg(game)
    await manager.broadcast_to_displays_raw(img_data)
    b64 = json.loads(img_data)["data"]
    try:
        await ws.send_text(json.dumps({"type": "trail_frame",   "data": b64}))
        await ws.send_text(json.dumps({"type": "trail_choices", "choices": game.choices()}))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Jurassic Park Security Game
# ---------------------------------------------------------------------------

_JP_FONT_PATHS = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Monaco.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]
_JP_BOLD_FONT_PATHS = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
]

def _jp_load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    paths = _JP_BOLD_FONT_PATHS if bold else _JP_FONT_PATHS
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()

# JP color palette
_JP_BG           = (20, 20, 40)
_JP_WHITE        = (220, 220, 220)
_JP_GREEN        = (0, 220, 0)
_JP_BRIGHT_GREEN = (0, 255, 0)
_JP_RED          = (255, 60, 60)
_JP_BRIGHT_RED   = (255, 0, 0)
_JP_AMBER        = (255, 200, 0)
_JP_CYAN         = (0, 200, 220)
_JP_DIM          = (80, 80, 100)
_JP_NEDRY_YELLOW = (255, 230, 80)

_JP_SYSTEMS = [
    {"id": "FENCES",  "label": "ELECTRIC FENCES",  "zone": "PERIMETER"},
    {"id": "DOORS",   "label": "DOOR LOCKS",        "zone": "VISITOR CTR"},
    {"id": "PHONES",  "label": "PHONE LINES",        "zone": "COMM ARRAY"},
    {"id": "RAPTORS", "label": "RAPTOR PEN LOCKS",  "zone": "PADDOCK C"},
]
_JP_DINOS = ["T-REX", "VELOCIRAPTORS", "DILOPHOSAURUS", "PTERANODON"]
_JP_NEDRY_TAUNTS = [
    "AH AH AH, YOU DIDN'T SAY",
    "THE MAGIC WORD!",
    "AH AH AH! AH AH AH!",
    "PLEASE! GOD DAMMIT!",
    "NOPE! NOPE! NOPE!",
]
_JP_BOOT_LINES = [
    "JURASSIC PARK SYSTEM",
    "UNIX SYSTEM V / SGI IRIX 4.0.5",
    "INGEN BIOTECH SECURITY v2.1",
    "LOADING MODULES ...",
    "PARK GRID ......... ONLINE",
    "SECURITY .......... ONLINE",
    "ALL SYSTEMS NOMINAL",
]
_JP_SHUTDOWN_MSGS = [
    "WHITE_RABBIT.OBJ EXECUTING ...",
    "ACCESS: SECURITY TRIPPED",
    "SYSTEM: DOOR LOCKS ... DISENGAGED",
    "SYSTEM: FENCES ...... OFFLINE",
    "SYSTEM: PHONES ...... DOWN",
    "SYSTEM: RAPTOR PEN .. UNLOCKED",
    "*** ALL SECURITY OFFLINE ***",
]


class JurassicGame:
    BOOT = "BOOT"; NORMAL = "NORMAL"; SHUTDOWN = "SHUTDOWN"
    RESTORE = "RESTORE"; MAGIC_WORD = "MAGIC_WORD"
    ESCAPED = "ESCAPED"; SECURED = "SECURED"

    def __init__(self):
        self.state = self.BOOT
        self.boot_step = 0
        self.shutdown_step = 0
        self.systems = {s["id"]: False for s in _JP_SYSTEMS}
        self.threat = 0
        self.said_magic_word = False
        self.nedry_lock_count = 0
        self.terminal_log: list[str] = []
        self.turns_taken = 0
        self.escaped_dino = None

    def reset(self):
        self.__init__()

    def advance_boot(self) -> bool:
        """Step boot animation. Returns True if more steps remain."""
        if self.state != self.BOOT:
            return False
        self.boot_step += 1
        if self.boot_step >= len(_JP_BOOT_LINES):
            self.state = self.NORMAL
            self.terminal_log = list(_JP_BOOT_LINES)
            self.terminal_log.append("TYPE ANYTHING TO CONTINUE")
            return False
        return True

    def advance_shutdown(self) -> bool:
        """Step shutdown animation. Returns True if more steps remain."""
        if self.state != self.SHUTDOWN:
            return False
        self.shutdown_step += 1
        if self.shutdown_step >= len(_JP_SHUTDOWN_MSGS):
            self.state = self.RESTORE
            self.terminal_log = [
                "*** NEDRY VIRUS ACTIVE ***",
                "RESTORE SYSTEMS BEFORE ESCAPE!",
                "",
            ]
            self._add_status_lines()
            self.terminal_log.append("TYPE SYSTEM NAME TO RESTORE")
            return False
        return True

    def handle_input(self, text: str, who: str = "VISITOR") -> list[str]:
        text_upper = text.strip().upper()
        if self.state == self.NORMAL:
            return self._handle_normal(text_upper)
        elif self.state == self.RESTORE:
            return self._handle_restore(text_upper)
        elif self.state == self.MAGIC_WORD:
            return self._handle_magic_word(text_upper)
        elif self.state in (self.ESCAPED, self.SECURED):
            return self._handle_end(text_upper)
        return []

    def _handle_normal(self, text: str) -> list[str]:
        self.state = self.SHUTDOWN
        self.shutdown_step = 0
        self.terminal_log = ["DODGSON! WE'VE GOT DODGSON HERE!"]
        return self.terminal_log[:]

    def _handle_restore(self, text: str) -> list[str]:
        self.turns_taken += 1
        if not self.said_magic_word:
            if any(w in text for w in {"PLEASE", "MAGIC WORD", "MAGIC", "PLEAS"}):
                self.said_magic_word = True
                self.terminal_log = ["ACCESS GRANTED.", "NEDRY LOCK BYPASSED.", ""]
                self._add_status_lines()
                self.terminal_log.append("TYPE SYSTEM NAME TO RESTORE")
                return self.terminal_log[:]
            else:
                self.state = self.MAGIC_WORD
                self.nedry_lock_count += 1
                self.threat = min(10, self.threat + 1)
                taunt = _JP_NEDRY_TAUNTS[min(self.nedry_lock_count - 1, len(_JP_NEDRY_TAUNTS) - 1)]
                self.terminal_log = [taunt]
                if self.nedry_lock_count == 1:
                    self.terminal_log.append("THE MAGIC WORD!")
                if self.threat >= 10:
                    return self._trigger_escape()
                return self.terminal_log[:]

        matched = None
        for s in _JP_SYSTEMS:
            if s["id"] in text or any(w in text for w in s["label"].split()):
                matched = s; break
            if len(text) >= 3 and text in s["id"]:
                matched = s; break

        if not matched:
            self.threat = min(10, self.threat + 1)
            self.terminal_log = [f"UNKNOWN SYSTEM: {text[:20]}"]
            self._add_status_lines()
            if self.threat >= 10:
                return self._trigger_escape()
            return self.terminal_log[:]

        if self.systems[matched["id"]]:
            self.terminal_log = [f"{matched['label']} ALREADY ONLINE."]
            self._add_status_lines()
            return self.terminal_log[:]

        self.systems[matched["id"]] = True
        self.terminal_log = [f"*** {matched['label']} RESTORED ***"]
        if all(self.systems.values()):
            self.state = self.SECURED
            self.terminal_log += ["", "ALL SYSTEMS RESTORED.", "PARK SECURE.",
                                   f"TURNS: {self.turns_taken}", "",
                                   "MR. HAMMOND, THE PHONES", "ARE WORKING."]
            return self.terminal_log[:]
        self._add_status_lines()
        remaining = sum(1 for v in self.systems.values() if not v)
        self.terminal_log.append(f"{remaining} SYSTEM(S) REMAINING")
        return self.terminal_log[:]

    def _handle_magic_word(self, text: str) -> list[str]:
        if any(w in text for w in {"PLEASE", "MAGIC WORD", "MAGIC", "PLEAS"}):
            self.said_magic_word = True
            self.state = self.RESTORE
            self.terminal_log = ["ACCESS GRANTED.", "NEDRY LOCK BYPASSED.", ""]
            self._add_status_lines()
            self.terminal_log.append("TYPE SYSTEM NAME TO RESTORE")
            return self.terminal_log[:]
        self.nedry_lock_count += 1
        self.threat = min(10, self.threat + 1)
        idx = min(self.nedry_lock_count - 1, len(_JP_NEDRY_TAUNTS) - 1)
        self.terminal_log = [_JP_NEDRY_TAUNTS[idx]]
        if self.threat >= 10:
            return self._trigger_escape()
        self.terminal_log.append(f"THREAT: {'#' * self.threat}{'.' * (10 - self.threat)}")
        return self.terminal_log[:]

    def _handle_end(self, text: str) -> list[str]:
        if any(w in text for w in {"PLAY", "AGAIN", "RESET", "RESTART", "YES", "NEW"}):
            self.reset()
            return ["REBOOTING ..."]
        return []

    def _trigger_escape(self) -> list[str]:
        self.state = self.ESCAPED
        self.escaped_dino = random.choice(_JP_DINOS)
        self.terminal_log = [
            f"*** {self.escaped_dino} HAS ESCAPED ***", "",
            "LIFE, UH ... FINDS A WAY.", "",
            "GAME OVER", f"TURNS: {self.turns_taken}",
            "", "TYPE 'PLAY AGAIN' TO RESTART",
        ]
        return self.terminal_log[:]

    def _add_status_lines(self):
        for s in _JP_SYSTEMS:
            on = self.systems[s["id"]]
            self.terminal_log.append(f" [{'OK' if on else 'XX'}] {s['label']}")
        if self.threat > 0:
            self.terminal_log.append(f"THREAT: {'#' * self.threat}{'.' * (10 - self.threat)}")

    def render(self, width: int = 375, height: int = 215) -> Image.Image:
        img = Image.new("RGB", (width, height), _JP_BG)
        draw = ImageDraw.Draw(img)
        self._render_header(draw, width)
        self._render_terminal(draw, width, height)
        self._apply_scanlines(img)
        return img

    def _render_header(self, draw: ImageDraw.ImageDraw, w: int):
        font = _jp_load_font(10, bold=True)
        draw.rectangle([0, 0, w, 14], fill=(10, 10, 30))
        draw.line([(0, 14), (w, 14)], fill=_JP_DIM)
        if self.state == self.ESCAPED:
            label, color = "JURASSIC PARK — CONTAINMENT BREACH", _JP_BRIGHT_RED
        elif self.state == self.SECURED:
            label, color = "JURASSIC PARK — SYSTEMS RESTORED", _JP_BRIGHT_GREEN
        elif self.state in (self.RESTORE, self.MAGIC_WORD):
            label, color = "JURASSIC PARK — SECURITY OFFLINE", _JP_AMBER
        else:
            label, color = "JURASSIC PARK SYSTEM", _JP_CYAN
        draw.text((6, 2), label, fill=color, font=font)
        if self.state in (self.RESTORE, self.MAGIC_WORD):
            threat_label = f"THREAT {self.threat}/10"
            bbox = draw.textbbox((0, 0), threat_label, font=font)
            tw = bbox[2] - bbox[0]
            tc = _JP_RED if self.threat >= 7 else (_JP_AMBER if self.threat >= 4 else _JP_GREEN)
            draw.text((w - tw - 6, 2), threat_label, fill=tc, font=font)

    def _render_terminal(self, draw: ImageDraw.ImageDraw, w: int, h: int):
        font = _jp_load_font(12)
        line_h = 16
        margin_x = 8
        top_y = 18
        max_lines = (h - top_y - 4) // line_h
        if self.state == self.BOOT:
            lines = _JP_BOOT_LINES[:self.boot_step]
        elif self.state == self.SHUTDOWN:
            lines = _JP_SHUTDOWN_MSGS[:self.shutdown_step]
        else:
            lines = self.terminal_log[-max_lines:]
        y = top_y
        for line in lines:
            if "***" in line and "ESCAPE" in line:      color = _JP_BRIGHT_RED
            elif "***" in line:                          color = _JP_BRIGHT_GREEN
            elif "AH AH AH" in line or "NOPE" in line: color = _JP_NEDRY_YELLOW
            elif "MAGIC WORD" in line:                  color = _JP_NEDRY_YELLOW
            elif line.startswith(" [XX]"):              color = _JP_RED
            elif line.startswith(" [OK]"):              color = _JP_GREEN
            elif "THREAT:" in line:                     color = _JP_AMBER
            elif "GAME OVER" in line:                   color = _JP_RED
            elif "RESTORED" in line or "SECURE" in line: color = _JP_BRIGHT_GREEN
            elif "ONLINE" in line or "NOMINAL" in line: color = _JP_GREEN
            elif "OFFLINE" in line or "DOWN" in line or "UNLOCKED" in line: color = _JP_RED
            elif "LIFE" in line or "FINDS A WAY" in line: color = _JP_AMBER
            elif "DODGSON" in line:                     color = _JP_AMBER
            elif "WHITE_RABBIT" in line:                color = _JP_RED
            elif "UNIX" in line or "INGEN" in line:    color = _JP_DIM
            elif "HAMMOND" in line or "PHONES" in line: color = _JP_CYAN
            elif "PLAY AGAIN" in line or "RESTART" in line: color = _JP_AMBER
            else:                                        color = _JP_WHITE
            draw.text((margin_x, y), line, fill=color, font=font)
            y += line_h
        if int(time.time() * 2) % 2 == 0:
            draw.text((margin_x, y), "_", fill=_JP_WHITE, font=font)

    def _apply_scanlines(self, img: Image.Image):
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        w, h = img.size
        for y in range(0, h, 4):
            odraw.line([(0, y), (w, y)], fill=(0, 0, 0, 40))
        composite = Image.alpha_composite(img.convert("RGBA"), overlay)
        img.paste(composite.convert("RGB"))


def _jp_frame_msg(game: JurassicGame) -> str:
    """Render current game state to a base64 JPEG stamp message."""
    img = game.render()
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return json.dumps({
        "type": "stamp", "data": f"data:image/jpeg;base64,{b64}",
        "x": 0.5, "y": 0.5, "w": 1.0, "h": 1.0, "r": 0, "ephemeral": True,
    })


_jurassic_game: JurassicGame | None = None
_jurassic_task: asyncio.Task | None = None
_jurassic_draw_ws: WebSocket | None = None


async def _jp_send_frame():
    if _jurassic_game is None:
        return
    img_data = _jp_frame_msg(_jurassic_game)
    await manager.broadcast_to_displays_raw(img_data)
    # Also send frame back to the draw client so they can see the game
    if _jurassic_draw_ws is not None:
        b64 = json.loads(img_data)["data"]
        try:
            await _jurassic_draw_ws.send_text(json.dumps({"type": "jurassic_frame", "data": b64}))
        except Exception:
            pass


async def _jp_boot_task():
    global _jurassic_game
    while _jurassic_game and _jurassic_game.state == JurassicGame.BOOT:
        _jurassic_game.advance_boot()
        await _jp_send_frame()
        await asyncio.sleep(0.3)


async def _jp_handle_chat(text: str, who: str):
    global _jurassic_game, _jurassic_task
    if _jurassic_game is None:
        return
    game = _jurassic_game
    prev_state = game.state
    game.handle_input(text, who)
    await _jp_send_frame()

    # Run shutdown animation
    if game.state == JurassicGame.SHUTDOWN:
        while game.state == JurassicGame.SHUTDOWN:
            game.advance_shutdown()
            await _jp_send_frame()
            await asyncio.sleep(0.5)
        await _jp_send_frame()

    # Run boot animation after reset
    if game.state == JurassicGame.BOOT:
        while _jurassic_game and _jurassic_game.state == JurassicGame.BOOT:
            _jurassic_game.advance_boot()
            await _jp_send_frame()
            await asyncio.sleep(0.3)
        await _jp_send_frame()


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


@app.get("/admin/moderation-log")
async def admin_moderation_log(password: str = ""):
    if password != ADMIN_PASSWORD:
        return JSONResponse({"error": "wrong password"}, status_code=401)
    try:
        con = sqlite3.connect(MODERATION_DB_FILE)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id, timestamp, ip, name, location, reason, session_duration FROM moderation_log ORDER BY timestamp DESC"
        ).fetchall()
        con.close()
        return JSONResponse([dict(r) for r in rows])
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


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
    global _last_visitor_time, _jurassic_game, _jurassic_task, _jurassic_draw_ws, _trail_game, _trail_draw_ws
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
                    if not message.get("ephemeral"):
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
                elif message["type"] == "jurassic_start":
                    if _jurassic_task:
                        _jurassic_task.cancel()
                    _jurassic_game = JurassicGame()
                    _jurassic_draw_ws = websocket
                    _jurassic_task = asyncio.create_task(_jp_boot_task())
                elif message["type"] == "jurassic_input":
                    if _jurassic_game is not None:
                        text = str(message.get("text", "")).strip()[:200]
                        if text:
                            asyncio.create_task(_jp_handle_chat(text, "YOU"))
                elif message["type"] == "jurassic_stop":
                    _jurassic_game = None
                    _jurassic_draw_ws = None
                    if _jurassic_task:
                        _jurassic_task.cancel()
                        _jurassic_task = None
                    await manager.broadcast_to_displays({"type": "sync", "history": manager.history})
                elif message["type"] == "trail_start":
                    _trail_game = OregonTrailGame()
                    _trail_draw_ws = websocket
                    await _trail_send(websocket, _trail_game)
                elif message["type"] == "trail_action":
                    if _trail_game is not None and _trail_draw_ws is websocket:
                        action = str(message.get("action", "")).strip()
                        if action:
                            _trail_game.handle(action)
                            await _trail_send(websocket, _trail_game)
                elif message["type"] == "trail_stop":
                    _trail_game = None
                    _trail_draw_ws = None
                    await manager.broadcast_to_displays({"type": "sync", "history": manager.history})
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
                            if _jurassic_game is not None:
                                city = from_label.split(",")[0].title() if from_label else "VISITOR"
                                asyncio.create_task(_jp_handle_chat(text, city))
    except WebSocketDisconnect:
        pass
    finally:
        if role == "draw":
            if _jurassic_game is not None:
                _jurassic_game = None
                _jurassic_draw_ws = None
                if _jurassic_task:
                    _jurassic_task.cancel()
                    _jurassic_task = None
            if _trail_draw_ws is websocket:
                _trail_game = None
                _trail_draw_ws = None
        manager.disconnect(websocket, role)
