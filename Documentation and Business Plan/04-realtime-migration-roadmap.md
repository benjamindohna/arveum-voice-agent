# 04 — Migration zur OpenAI Realtime API

Roadmap für den Wechsel vom aktuellen "STT → LLM → TTS"-Pipeline-Modell zu **streaming, sub-sekünder** Voice-Konversation.

## Stand heute (April 2026)

Aktuelle Pipeline pro User-Turn:

```
User-Sprache → Silero VAD → Whisper STT → Claude → OpenAI TTS → Wiedergabe
       0 ms     ~50 ms      ~800 ms       ~1.2 s    ~1.0 s
```

Gesamt-Latenz: **~3 s** (Best Case mit tts-1, Haiku 4.5)
Bottleneck: jede Stufe wartet auf vollständigen Output der vorherigen.

## Ziel-Architektur: OpenAI Realtime API

### Was sie löst

- **Sub-1-s-Latenz**: Audio-Streaming end-to-end. Erste Audio-Bytes ~500 ms nach User-Sprachende.
- **Native deutsche Aussprache**: Realtime-Stimmen sind multilingual und behandeln Anglizismen besser als batched TTS.
- **Eingebaute VAD**: Server-seitig, hochpräzise, keine externe Library nötig.
- **Funktion-Calls inline**: Tools werden während des Streams ausgelöst — kein separater Round-Trip.
- **Interruption nativ**: API erkennt Barge-In und stoppt Generierung sauber.

### Wie sie funktioniert

WebSocket-basiert. Vereinfacht:

```
Browser ←──── WebSocket ────→ OpenAI Realtime API
   ↑              ↓                    ↓
   Mic Audio →    →   GPT-4o → TTS →   ← Audio-Bytes
   (Opus)         ↓                    ↑
                  Tool-Calls → Browser   (PCM16)
                  ↑              ↓
                  ←──── Tool-Results ──┘
```

Ein einziger Stream. Audio in beide Richtungen, Function-Calls als Events dazwischen.

### Wichtige API-Details

- **Endpoint**: `wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-12-17` (oder neuere)
- **Audio-Format**: PCM16 mono 24kHz (Standard)
- **Stimmen**: `alloy`, `ash`, `ballad`, `coral`, `echo`, `sage`, `shimmer`, `verse` — selbe wie tts-1-hd, aber streaming
- **Tools**: identisch zu Claude Tool Use, JSON-Schema-Definition

## Was sich im Code ändert

### Was BLEIBT

- ✅ Datenmodell (`STATE.history`, `STATE.questions`, etc.)
- ✅ Mock-Daten (`data/*.json`)
- ✅ Tool-Handler-Logik (`list_open_jobs`, `record_answer`, etc.)
- ✅ UI-Layout (Dashboard, Log, Email-Modal)
- ✅ State-Machine (Free/Apply Mode-Konzept)
- ✅ System-Prompt-Inhalte

### Was sich ÄNDERT

| Komponente | Heute | Realtime |
|---|---|---|
| Voice-Subsystem | Silero VAD + MediaRecorder | WebSocket-Stream + WebAudio |
| STT | Whisper API (REST) | Streaming (built-in) |
| LLM | Claude Haiku/Sonnet (REST) | GPT-4o-realtime (WSS) |
| TTS | OpenAI tts-1 (REST) | Streaming (built-in) |
| Tool-Use | Claude Tool Use | OpenAI Realtime Function Calls |
| Latenz pro Turn | ~3 s | ~500–800 ms |

### Architektur-Skizze für die neue Voice-Klasse

```js
class RealtimeAgent {
    constructor(config, tools, systemPrompt) {
        this.ws = null;
        this.audioCtx = new AudioContext({ sampleRate: 24000 });
        this.tools = tools;
    }

    async connect() {
        this.ws = new WebSocket(`wss://api.openai.com/v1/realtime?model=${MODEL}`, [
            'realtime',
            `openai-insecure-api-key.${OPENAI_KEY}`,
            'openai-beta.realtime-v1'
        ]);

        this.ws.onopen = () => this.sendSessionUpdate();
        this.ws.onmessage = (e) => this.handleEvent(JSON.parse(e.data));

        await this.startMicCapture();   // sendet PCM16-Chunks via append-audio
    }

    sendSessionUpdate() {
        this.ws.send(JSON.stringify({
            type: 'session.update',
            session: {
                modalities: ['text', 'audio'],
                voice: 'shimmer',
                instructions: this.systemPrompt,
                tools: this.tools,
                input_audio_transcription: { model: 'whisper-1' },
                turn_detection: { type: 'server_vad', threshold: 0.5, silence_duration_ms: 4500 },
            }
        }));
    }

    handleEvent(event) {
        switch (event.type) {
            case 'response.audio.delta':
                this.playAudioChunk(event.delta);  // base64 PCM16 → AudioBuffer → play
                break;
            case 'response.function_call_arguments.done':
                this.handleToolCall(event);  // executeTool() wie heute
                break;
            case 'input_audio_buffer.speech_started':
                this.onUserSpeechStart();  // optional UI-Update
                break;
            case 'response.audio_transcript.delta':
                this.appendAgentTranscript(event.delta);
                break;
            case 'conversation.item.input_audio_transcription.completed':
                this.appendUserTranscript(event.transcript);
                break;
            // ... viele weitere Events
        }
    }
}
```

## Migration in Phasen

### Phase 1 — Vorbereitung (jetzt)
- [x] Stabiler MVP mit Silero VAD läuft (löst die meisten aktuellen Voice-Bugs)
- [ ] Tool-Definitionen abstrahieren — heute Claude-spezifisch, müssen für OpenAI Function-Calls portabel werden
- [ ] System-Prompt in eigenes Modul (heute in `buildSystemPrompt()`)
- [ ] WebSocket-Test-Setup gegen Realtime API mit minimalem Echo-Test

### Phase 2 — Realtime-Spike (1–2 Tage)
- [ ] Neue Datei `realtime-agent.js` mit `RealtimeAgent`-Klasse
- [ ] Nur Free-Mode implementieren — User redet, Agent antwortet, ein Tool (`list_open_jobs`)
- [ ] Audio-Pipeline testen: Mic → WS, WS → Lautsprecher
- [ ] Latenz messen und dokumentieren

### Phase 3 — Feature-Parity (3–5 Tage)
- [ ] Alle Tools portieren (`get_benefit`, `send_upload_link`, `record_answer`, `extend_previous_answer`, `escalate_to_human`)
- [ ] State-Machine an Realtime-Events binden (Free/Apply/Interview/Wrapping)
- [ ] CV-Upload-Flow (parallel zu Realtime-Stream weiterhin Claude für PDF-Analyse — Realtime kann keine PDFs)
- [ ] Email-Buchstabier-Bestätigung (im System-Prompt, gleiches Pattern wie heute)
- [ ] Toggle im UI: "Realtime Mode (Beta)" vs. "Pipeline Mode"

### Phase 4 — Polish (1–2 Tage)
- [ ] Server-VAD vs. Client-VAD vergleichen, beste Konfiguration finden
- [ ] Reconnect-Logik bei WS-Drops
- [ ] Token/Audio-Cost-Tracking im Log
- [ ] Failover auf Pipeline-Mode bei Realtime-Fehler

## Caveats

### 1. Kein Anthropic Claude
Realtime API ist OpenAI-exklusiv. **Wir verlieren Claude.** Wenn Claude-spezifische Stärken (PDF-Verständnis, Reasoning-Tiefe) wichtig sind, müssen wir Hybrid-Modus bauen:
- Realtime für Voice-Konversation
- Claude für Hintergrund-Tasks (CV-Analyse, Frage-Generierung, Scoring)

Das macht der heutige MVP technisch gesehen schon — generateQuestionsFromCv und scoreCandidate sind separate Claude-Calls. Lässt sich beibehalten.

### 2. Kosten
Realtime API ist deutlich teurer:
- Audio-Input: ~$100/M tokens (~$0.06/min)
- Audio-Output: ~$200/M tokens (~$0.24/min)
- Ein 15-min-Bewerbungsgespräch: **~$4.50 in Audio-Tokens**

Vergleich Pipeline heute:
- Whisper: ~$0.006/min × 15 = $0.09
- Claude Haiku: ~$0.10–0.30 für ganzes Gespräch
- TTS-1: ~$0.015/min × 7 (Aria spricht ca. 50%) = $0.10
- **Total ~$0.30–0.50 pro 15-min-Gespräch**

Realtime ist **~10× teurer**. Für Sales-Pitches und Demos egal. Für Production-Skalierung relevant — Pricing-Modell muss das einkalkulieren.

### 3. PDF-Verständnis fehlt
Realtime API kann keine PDFs lesen. CV-Analyse muss separat laufen (Claude oder GPT-4o batch).

### 4. Beta-Status
"gpt-4o-realtime-preview" — explicit Beta. Breaking Changes möglich. Production-Use mit Vorsicht.

## Alternativen bewerten

### Alternative A: Vapi
Voice-Agent-Plattform mit eigener Pipeline. Eigene Knobs für STT/LLM/TTS-Provider, eigene Latenz-Optimierungen.
- ✅ Provider-Wahl (Claude möglich, ElevenLabs, Deepgram, etc.)
- ✅ Production-ready, Telefon-Nummern, etc.
- ❌ Vendor-Lock-in
- ❌ ~$0.05/min Plattformgebühr + Provider-Kosten
- ❌ Weniger Kontrolle über UX-Details

### Alternative B: LiveKit Agents
Open Source, self-hostable Voice-Agent-Framework.
- ✅ Provider-flexibel
- ✅ Self-host = kontrolle + niedrigere Kosten
- ❌ Mehr Engineering-Aufwand
- ❌ Python-basiert (Server) — passt nicht ganz zum Browser-MVP

### Alternative C: Pipecat
Daily's Open-Source Voice-Agent-Framework. Sehr nah an LiveKit-Ansatz.

### Empfehlung
**Phase 2 mit OpenAI Realtime direkt** — schnellster Weg zu sub-1s-Latenz, einfachster Tech-Stack (Browser-only). Wenn Production-Skalierung absehbar wird → Vapi oder LiveKit als zweite Phase.

## Was bleibt offen für die Entscheidung

1. **Akzeptieren wir den Verlust von Claude in der Live-Konversation?** Wenn Claude für Tonalität/Empathie wichtig ist, sollten wir Hybrid (Realtime für Voice, Claude für Background) sauber bauen.
2. **Kosten-Toleranz**: 10× Audio-Kosten — bei welchem Use-Case wirtschaftlich?
3. **Telefon-Integration**: Realtime ist Browser-API. Für echte Telefon-Nummern brauchen wir Twilio + Realtime-Bridge oder direkt Vapi.

---

Sobald du grünes Licht gibst, kann ich in Phase 1 + 2 starten — Tool-Abstraktion sauber + minimaler Realtime-Spike. ~1 Tag bis erstes "Hello-World"-Telefonat über Realtime API.
