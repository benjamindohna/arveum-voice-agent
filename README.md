# Arveum Voice Agent — MVP

Voice-Recruitment-Agent: Bewerber sprechen mit einer KI über offene Stellen, laden ihren Lebenslauf hoch, und führen ein adaptives Interview. Recruiter sehen Score und Highlights im Dashboard.

Aktueller Stand: **Browser-basierter MVP mit Python-Backend** (Schritt vor echter Telefonie via Twilio).

## Architektur

```
Browser (Mic + Speaker + UI)        Python Backend
─────────────────────────           ──────────────────
frontend/                ↔  WSS  ↔  backend/
  index.html                          ├── voice_bridge.py
  app.js                              ├── tools.py
  styles.css                          ├── prompts.py
                                      ├── llm.py (Anthropic Claude)
                                      ├── email_service.py
                                      └── data/
                                              ↕
                                      OpenAI Realtime API
                                      Anthropic Claude API
```

Browser ist **dünner Client**: Mikrofon-Audio aufnehmen, Audio abspielen, UI rendern.
Backend ist **autoritative Quelle**: hält API-Keys, fährt OpenAI Realtime + Claude, Tool-Execution, State-Management, Email-Versand.

## Folder-Struktur

```
mvp-call-agent/
├── backend/                          Python-Backend (FastAPI)
│   ├── main.py                       FastAPI App + WebSocket-Endpoint + Static-Mount
│   ├── voice_bridge.py               Pro-Session Bridge Browser ↔ OpenAI Realtime
│   ├── session.py                    Per-Call State (mode, buffer, answers, ...)
│   ├── tools.py                      Tool-Definitionen + Handler
│   ├── prompts.py                    System-Prompt, Greeting, Handoff-Text
│   ├── llm.py                        Anthropic Claude (CV-Analyse + Scoring)
│   ├── email_service.py              Mock + (Phase B) Resend-Stub
│   ├── data/                         Mock-Daten als JSON
│   ├── requirements.txt
│   ├── .env.example                  Template für API-Keys
│   └── README.md
│
├── frontend/                         JavaScript-Frontend (thin client)
│   ├── index.html
│   ├── app.js                        WebSocket-Client + Mic + Speaker + UI
│   ├── styles.css
│   ├── data/                         (Fallback für Standalone-Modus)
│   └── README.md
│
├── Documentation and Business Plan/  Diagramme + Business-Plan + Roadmap
│   ├── 01-user-journey.md
│   ├── 02-agent-state-machine.md
│   ├── 03-backend-architecture.md
│   ├── 04-realtime-migration-roadmap.md
│   └── 05-production-architecture-plan.md
│
├── test-cv-anna-mueller.pdf          Test-Lebenslauf für End-to-End-Demo
└── README.md                         (du bist hier)
```

## Schnellstart

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env editieren: OPENAI_API_KEY und ANTHROPIC_API_KEY eintragen
uvicorn main:app --reload --port 8000
```

Dann im Browser: **http://localhost:8000**

FastAPI liefert das Frontend (`../frontend/`) gleich mit aus.

## Test-Walkthrough

1. **Anruf starten** klicken → Aria spricht die Begrüßung (verbatim, nicht unterbrechbar)
2. Frei reden — z.B. *"Was macht ihr eigentlich?"*, *"Wie viele Urlaubstage habt ihr?"*, *"Welche Stellen sind offen?"*
3. Wenn du dich bewerben willst → Aria fragt nach Email (mit "Klammeraffe" buchstabieren!)
4. Email-Modal poppt auf → **Lebenslauf hochladen** (`test-cv-anna-mueller.pdf` aus diesem Ordner)
5. Aria überlegt sich Fragen → adaptives Interview (8 Fragen Default)
6. Am Ende: Score + Highlights im Recruiter-Dashboard

## Was funktioniert

- **Verbatim Begrüßung** mit AI-Disclosure (EU AI Act konform)
- **Server-VAD via OpenAI Realtime** — kontinuierliches Hören, Barge-In sauber
- **Tool-Disziplin im Interview** (nur record_answer / extend_previous_answer / escalate_to_human)
- **Buffer-basierte Antwort-Sammlung** für mehrteilige Antworten mit Pausen
- **Mensch-Übergabe** mit verbatim Übergangs-Ansage und sauberem Call-Ende
- **CV-Upload** via Realtime-Bridge → Claude multimodal generiert rollenspezifische Fragen
- **Live-Log** im UI zeigt jeden Schritt (STT, LLM-Calls, Tool-Calls, VAD-Events)
- **Mock-Email-Modal** simuliert den Magic-Link-Flow

## Was als nächstes kommt

**Phase B** (Backend-Erweiterungen, ~1 Woche):
- Echter Email-Versand via Resend (Stub vorhanden in `backend/email_service.py`)
- SQLite/Postgres für Bewerber-Daten + Mandanten-Konfig
- Auth + Recruiter-Login

**Phase C** (Telefonie, ~2 Wochen):
- Twilio + Pipecat-Bridge für echte Telefonnummern
- Hunderte parallele Calls über zentrale Server-Pools
- Frontend wird optional (Browser-Embed bleibt als Web-Variante verfügbar)

Roadmap-Details: `Documentation and Business Plan/05-production-architecture-plan.md`

## Branch-Historie (vor diesem Repo)

Während der Exploration-Phase entstanden drei Branches im alten Experiment-Repo:
1. **main** — initialer Browser-Only-MVP (Pipeline + Realtime-Toggle)
2. **realtime-only** — Cleanup auf Realtime-Only-Modus
3. **production-architecture** — Migration zu Python-Backend + Thin-Client

Dieses Repo startet von dem `production-architecture`-Stand als sauberer Initial Commit. Die Exploration-Historie liegt unter github.com/benjamindohna/Arveum-voice-agent-experiment.
