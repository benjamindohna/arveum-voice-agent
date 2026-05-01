# Arveum Backend (Python)

Python-Backend für den Voice-Recruitment-Agent. Bridge zwischen Browser und OpenAI Realtime API,
plus Anthropic-Calls für CV-Analyse + Scoring.

Architektur: siehe `Documentation and Business Plan/05-production-architecture-plan.md`.

## Setup

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env editieren — OPENAI_API_KEY + ANTHROPIC_API_KEY eintragen
```

## Start

```bash
uvicorn main:app --reload --port 8000
```

Browser auf http://localhost:8000 öffnen — FastAPI liefert das Frontend mit aus `../mvp-call-agent/`.

## Health-Check

```bash
curl http://localhost:8000/api/health
```

Sollte `{"status":"ok","openai_key":true,"anthropic_key":true,...}` zurückgeben.

## Architektur

```
backend/
├── main.py              FastAPI: /ws/voice + /api/data/* + Static-Frontend-Mount
├── voice_bridge.py      Pro-Session Bridge Browser ↔ OpenAI Realtime
├── session.py           Session-State (mode, buffer, answers, ...)
├── tools.py             Tool-Definitionen + Handler (record_answer, send_upload_link, etc.)
├── prompts.py           System-Prompt, Greeting, Handoff-Text
├── llm.py               Anthropic Claude (Question-Gen aus PDF + Scoring)
├── email_service.py     Mock + (Phase B) Resend
├── data/                Mock-Daten (Firma, Stellen, Benefits, Standorte)
└── .env                 OPENAI_API_KEY + ANTHROPIC_API_KEY
```

## Datenfluss (Live-Voice)

```
Mikrofon (Browser) → AudioWorklet (PCM16) → WebSocket /ws/voice
                                              │
                                              ▼
                                          VoiceBridge
                                              │ forward audio
                                              ▼
                                       OpenAI Realtime WSS
                                              │ events (audio, transcript, tool_call)
                                              ▼
                                          VoiceBridge
                              ┌──────────────┴───────────────┐
                              ▼                              ▼
                         Tools ausführen              Audio + Transcripts
                         (Python-Handler)              an Browser pushen
                              │                              │
                              ▼                              ▼
                         Result an OpenAI               Browser spielt ab
                         (function_call_output)          (PCM16-Queue)
```

## Geplante nächste Schritte (Phase B/C)

- **Phase B**: Real-Email-Versand via Resend (`ResendEmailService` swap-in für `MockEmailService`)
- **Phase B**: SQLite/Postgres-Adapter (Mandanten-Konfig statt JSON-Mock)
- **Phase C**: Twilio-Adapter — gleicher Bridge-Code, andere Audio-Source (SIP statt Browser-WebSocket)
