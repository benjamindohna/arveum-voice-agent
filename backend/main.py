"""FastAPI-Einstiegspunkt: WebSocket /ws/voice + statisches Frontend.

Start: cd backend && uvicorn main:app --reload --port 8000
Browser: http://localhost:8000
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from email_service import MockEmailService
from voice_bridge import VoiceBridge


# .env aus backend/ laden
load_dotenv(Path(__file__).parent / ".env")

EMAIL_SERVICE = MockEmailService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    backend_url = os.environ.get("VOICE_BACKEND_URL", "https://voice.arveum.ai")
    print(f"Backend bereit. Stellen-Daten kommen von {backend_url}.")
    if not os.environ.get("OPENAI_API_KEY"):
        print("⚠️  OPENAI_API_KEY nicht gesetzt — Calls werden mit Fehler enden.")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("⚠️  ANTHROPIC_API_KEY nicht gesetzt — Question-Gen + Scoring werden fehlschlagen.")
    yield


app = FastAPI(lifespan=lifespan)


@app.websocket("/ws/voice")
async def voice_endpoint(ws: WebSocket):
    await ws.accept()
    bridge = VoiceBridge(ws, EMAIL_SERVICE)
    try:
        await bridge.run()
    except WebSocketDisconnect:
        pass


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "openai_key": bool(os.environ.get("OPENAI_API_KEY")),
        "anthropic_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "voice_backend_url": os.environ.get("VOICE_BACKEND_URL", "https://voice.arveum.ai"),
    }


# Frontend statisch unter / servieren — liegt im Schwester-Ordner ../frontend/
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
