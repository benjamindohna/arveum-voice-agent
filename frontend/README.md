# Arveum Frontend (Thin Client)

Browser-Frontend für den Voice-Recruitment-Agent. **Reine UI + Audio-I/O** — alle Voice-Logik, OpenAI- und Anthropic-Calls, Email-Versand, Tool-Execution laufen im Python-Backend.

## Architektur

```
Browser (mvp-call-agent/)        ←→        Python Backend (../backend/)
  • UI                            WS         • OpenAI Realtime API
  • Mic-Capture (PCM16)        ↔  WS  ↔     • Anthropic Claude (CV + Scoring)
  • Audio-Wiedergabe                         • Email-Versand
                                              • State-Management
                                              • Tool-Execution
```

## Setup

Backend muss laufen — siehe `../backend/README.md`. Wenn das Backend auf Port 8000 läuft, servt es das Frontend gleich mit aus → Browser auf **http://localhost:8000** öffnen.

## Frontend-Files

- `index.html` — UI (Konfig, Transcript, Dashboard, Log-Panel, Email-Modal)
- `styles.css` — Styling
- `app.js` — WebSocket-Client zum Backend, Mic-Capture, Audio-Wiedergabe, UI-Updates
- `data/*.json` — Mock-Daten (Backend hat dieselben in `backend/data/`; Frontend lädt sie zum Anzeigen im Kontext-Panel via `/api/data/*`)

## Was im Frontend nicht (mehr) ist

- Keine API-Keys (liegen sicher in `backend/.env`)
- Kein direkter OpenAI/Anthropic-Call (Backend macht das)
- Kein Silero VAD (server-VAD via OpenAI Realtime)
- Kein Pipeline-Modus (nur Realtime)

Alles in einem Browser-Tab vorher → jetzt: Browser ist UI/Audio-I/O, Backend ist die Logik.
