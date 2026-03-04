import asyncio
import json
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

CAMERA_URL = "http://10.0.0.8:8080/?action=snapshot"
POLL_INTERVAL = 0.1  # seconds

app = FastAPI()
templates = Jinja2Templates(directory="templates")

_latest_frame: bytes | None = None


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

    async def connect(self, websocket: WebSocket, role: str):
        await websocket.accept()
        if role == "draw":
            self.draw_clients.append(websocket)
        elif role == "display":
            self.display_clients.append(websocket)
            await websocket.send_text(
                json.dumps({"type": "sync", "history": self.history})
            )

    def disconnect(self, websocket: WebSocket, role: str):
        if role == "draw" and websocket in self.draw_clients:
            self.draw_clients.remove(websocket)
        elif role == "display" and websocket in self.display_clients:
            self.display_clients.remove(websocket)

    def update_history(self, message: dict):
        if message["type"] == "clear":
            self.history.clear()
        elif message["type"] == "stroke":
            self.history.append(message)

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


@app.get("/")
async def root():
    return RedirectResponse(url="/draw")


@app.get("/draw", response_class=HTMLResponse)
async def draw_page(request: Request):
    return templates.TemplateResponse("draw.html", {"request": request})


@app.get("/display", response_class=HTMLResponse)
async def display_page(request: Request):
    return templates.TemplateResponse("display.html", {"request": request})


@app.get("/snapshot")
async def snapshot():
    if _latest_frame is None:
        return Response(status_code=503)
    return Response(content=_latest_frame, media_type="image/jpeg")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, role: str = "draw"):
    await manager.connect(websocket, role)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            manager.update_history(message)
            await manager.broadcast_to_displays(message)
    except WebSocketDisconnect:
        manager.disconnect(websocket, role)
