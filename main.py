import asyncio
import ipaddress
import json
import os
import time
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

CAMERA_URL = "http://10.0.0.8:8080/?action=snapshot"
POLL_INTERVAL = 0.1  # seconds
ARTWORK_FILE = "artwork_history.json"
MAX_ARTWORK = 25
GUESTBOOK_FILE = "guestbook.json"
MAX_GUESTBOOK = 200

app = FastAPI()
templates = Jinja2Templates(directory="templates")

_latest_frame: bytes | None = None
_geo_cache: dict[str, str] = {}


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
    if ip in _geo_cache:
        return _geo_cache[ip]
    if not ip or _is_private(ip):
        _geo_cache[ip] = ""
        return ""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(
                f"http://ip-api.com/json/{ip}?fields=city,regionName,country"
            )
            if r.status_code == 200:
                data = r.json()
                parts = [data.get("city", ""), data.get("regionName", ""), data.get("country", "")]
                location = ", ".join(p for p in parts if p)
                _geo_cache[ip] = location
                return location
    except Exception:
        pass
    _geo_cache[ip] = ""
    return ""


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
    asyncio.create_task(_poll_camera())


class ConnectionManager:
    def __init__(self):
        self.draw_clients: list[WebSocket] = []
        self.display_clients: list[WebSocket] = []
        self.history: list[dict] = []
        self._client_ips: dict[int, str] = {}  # id(websocket) → ip
        self.session_start: float | None = None

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

    def disconnect(self, websocket: WebSocket, role: str):
        if role == "draw" and websocket in self.draw_clients:
            self.draw_clients.remove(websocket)
            self._client_ips.pop(id(websocket), None)
            if not self.draw_clients:
                self.session_start = None
        elif role == "display" and websocket in self.display_clients:
            self.display_clients.remove(websocket)

    def update_history(self, message: dict):
        if message["type"] in ("stroke", "stamp"):
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

        if clear_history:
            self.history.clear()
        if clear_display:
            await self.broadcast_to_displays({"type": "clear"})

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
    return templates.TemplateResponse("home.html", {"request": request})


@app.get("/draw", response_class=HTMLResponse)
async def draw_page(request: Request):
    return templates.TemplateResponse("draw.html", {"request": request})


@app.get("/display", response_class=HTMLResponse)
async def display_page(request: Request):
    return templates.TemplateResponse("display.html", {"request": request})


@app.get("/status")
async def status():
    drawing = len(manager.draw_clients) > 0
    elapsed = (time.time() - manager.session_start) if manager.session_start is not None else None
    return JSONResponse({"drawing": drawing, "session_elapsed": elapsed})


@app.get("/snapshot")
async def snapshot():
    if _latest_frame is None:
        return Response(status_code=503)
    return Response(content=_latest_frame, media_type="image/jpeg")


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
    entry = {"name": name, "message": message, "location": location, "time": time.time()}
    entries = _load_guestbook()
    entries.append(entry)
    if len(entries) > MAX_GUESTBOOK:
        entries = entries[-MAX_GUESTBOOK:]
    _save_guestbook(entries)
    return JSONResponse({"ok": True})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, role: str = "draw"):
    await manager.connect(websocket, role)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            if role == "draw":
                if message["type"] in ("stroke", "stamp"):
                    if not manager.history:
                        await manager.broadcast_to_displays({"type": "clear"})
                    manager.update_history(message)
                    await manager.broadcast_to_displays(message)
                elif message["type"] == "finish":
                    name = str(message.get("name", "Anonymous")).strip() or "Anonymous"
                    duration = int(message.get("duration", 0))
                    await manager.end_session(websocket, name, duration, clear_display=False, clear_history=False)
                elif message["type"] == "redraw":
                    manager.history = [m for m in message.get("history", []) if m.get("type") in ("stroke", "stamp")]
                    await manager.broadcast_to_displays({"type": "sync", "history": manager.history})
                elif message["type"] == "clear":
                    name = str(message.get("name", "Anonymous")).strip() or "Anonymous"
                    duration = int(message.get("duration", 0))
                    await manager.end_session(websocket, name, duration, clear_display=True)
    except WebSocketDisconnect:
        manager.disconnect(websocket, role)
