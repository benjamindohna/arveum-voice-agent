"""FastAPI-Einstiegspunkt: WebSocket /ws/voice + statisches Frontend.

Start: cd backend && uvicorn main:app --reload --port 8000
Browser: http://localhost:8000
"""

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from email_service import MockEmailService
from voice_bridge import VoiceBridge


# .env aus backend/ laden
load_dotenv(Path(__file__).parent / ".env")

# Mock-Daten beim Start einmalig in den Speicher
DATA_DIR = Path(__file__).parent / "data"
DATA = {
    "company": json.loads((DATA_DIR / "company.json").read_text(encoding="utf-8")),
    "jobs": json.loads((DATA_DIR / "jobs.json").read_text(encoding="utf-8"))["jobs"],
    "benefits": json.loads((DATA_DIR / "benefits.json").read_text(encoding="utf-8")),
    "locations": json.loads((DATA_DIR / "locations.json").read_text(encoding="utf-8"))["locations"],
}

EMAIL_SERVICE = MockEmailService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(
        f"Backend bereit. {len(DATA['jobs'])} Stellen, {len(DATA['benefits'])} Benefits, "
        f"{len(DATA['locations'])} Standorte geladen."
    )
    if not os.environ.get("OPENAI_API_KEY"):
        print("⚠️  OPENAI_API_KEY nicht gesetzt — Calls werden mit Fehler enden.")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("⚠️  ANTHROPIC_API_KEY nicht gesetzt — Question-Gen + Scoring werden fehlschlagen.")
    yield


app = FastAPI(lifespan=lifespan)


@app.websocket("/ws/voice")
async def voice_endpoint(ws: WebSocket):
    await ws.accept()
    bridge = VoiceBridge(ws, DATA, EMAIL_SERVICE)
    try:
        await bridge.run()
    except WebSocketDisconnect:
        pass


@app.get("/api/data/{filename}")
async def get_mock_data(filename: str):
    """Frontend lädt Mock-Daten zum Anzeigen im Kontext-Panel."""
    safe_files = {"company.json", "jobs.json", "benefits.json", "locations.json"}
    if filename not in safe_files:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return FileResponse(DATA_DIR / filename, media_type="application/json")


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "openai_key": bool(os.environ.get("OPENAI_API_KEY")),
        "anthropic_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "jobs": len(DATA["jobs"]),
    }


# Frontend statisch unter / servieren — liegt im Schwester-Ordner ../frontend/
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
