"""Pro-WebSocket-Bridge zwischen Browser und OpenAI Realtime API.

Hier liegt die gesamte Voice-Orchestrierung: Audio-Forwarding in beide Richtungen,
Tool-Call-Routing, Verbatim-Greeting, Mensch-Übergabe-Flow, CV-Upload-Trigger.

Architektur:
- Browser ↔ uns (Audio + Control-Events via JSON-WebSocket-Frames)
- Wir ↔ OpenAI Realtime (raw OpenAI Realtime Events via WSS mit Bearer-Auth)
- Browser ist dünner Klient (Mic, Speaker, UI). Wir sind autoritative Quelle.
"""

import asyncio
import json
import os
from typing import Any

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from session import VoiceSession
from prompts import build_system_prompt, REALTIME_GREETING, HUMAN_HANDOFF_MESSAGE
from tools import execute_tool, ToolContext, tools_for_mode
from email_service import EmailService
from llm import generate_questions_from_cv, score_candidate


OPENAI_REALTIME_URL_TEMPLATE = "wss://api.openai.com/v1/realtime?model={model}"


class VoiceBridge:
    def __init__(self, browser_ws: WebSocket, data: dict, email_service: EmailService):
        self.browser_ws = browser_ws
        self.data = data
        self.email_service = email_service
        self.session = VoiceSession()
        self.openai_ws: websockets.WebSocketClientProtocol | None = None
        self.openai_listener_task: asyncio.Task | None = None
        self.pending_continuation = False
        # Async-Events für Wait-Patterns (waitForResponseAndPlaybackDone-Äquivalent)
        self._response_done_event = asyncio.Event()
        self._playback_drained_event = asyncio.Event()

    # ─── Hauptschleife: Browser-Frames empfangen ───────────────────────
    async def run(self):
        try:
            while True:
                raw = await self.browser_ws.receive_text()
                msg = json.loads(raw)
                await self._handle_browser_message(msg)
        except WebSocketDisconnect:
            pass
        except Exception as e:
            await self._safe_send_browser({"type": "log", "logtype": "err", "message": f"Browser-WS Fehler: {e}"})
        finally:
            await self._cleanup()

    # ─── Browser → Bridge ───────────────────────────────────────────────
    async def _handle_browser_message(self, msg: dict):
        msg_type = msg.get("type")

        if msg_type == "start_call":
            await self._start_call(msg.get("config", {}))

        elif msg_type == "audio_chunk":
            # PCM16 base64 chunk vom Mikrofon → direkt zur Realtime-API
            if self.openai_ws and not self.session.muted:
                await self._openai_send({"type": "input_audio_buffer.append", "audio": msg["data"]})

        elif msg_type == "cv_uploaded":
            await self._handle_cv_upload(msg)

        elif msg_type == "playback_drained":
            # Browser meldet: Audio-Queue ist leer
            self._playback_drained_event.set()

        elif msg_type == "mute":
            self.session.muted = bool(msg.get("muted", False))
            if self.session.muted and self.openai_ws:
                # Verhindern, dass schon gepufferter User-Audio nach Unmute auto-committed wird
                await self._openai_send({"type": "input_audio_buffer.clear"})

        elif msg_type == "end_call":
            await self._end_call()

    # ─── Call-Start: Realtime-Verbindung + Begrüßung ───────────────────
    async def _start_call(self, config: dict):
        self.session.reset_for_new_call()
        self.session.openai_voice = config.get("openaiVoice", "shimmer")
        self.session.realtime_model = config.get("realtimeModel", "gpt-realtime")
        self.session.backend_llm_model = config.get("backendLlmModel", "claude-haiku-4-5")
        try:
            self.session.question_count = int(config.get("questionCount", 8))
        except (TypeError, ValueError):
            self.session.question_count = 8

        await self.send_to_browser({
            "type": "log", "logtype": "sys",
            "message": f"=== Call gestartet (Voice: {self.session.openai_voice}, Model: {self.session.realtime_model}) ===",
        })
        await self.send_to_browser({"type": "state_update", "state": self.session.to_dashboard_dict(self.data)})
        await self.send_to_browser({"type": "status", "text": "Call aktiv", "className": "active"})

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            await self.send_to_browser({
                "type": "error",
                "message": "OPENAI_API_KEY nicht im Backend gesetzt. Bitte in backend/.env eintragen.",
            })
            return

        url = OPENAI_REALTIME_URL_TEMPLATE.format(model=self.session.realtime_model)
        try:
            self.openai_ws = await websockets.connect(
                url,
                additional_headers={
                    "Authorization": f"Bearer {api_key}",
                    "OpenAI-Beta": "realtime=v1",
                },
                max_size=None,
            )
        except Exception as e:
            await self.send_to_browser({"type": "error", "message": f"Realtime-Verbindung fehlgeschlagen: {e}"})
            return

        await self.send_to_browser({"type": "log", "logtype": "sys", "message": "Realtime WebSocket verbunden"})
        self.openai_listener_task = asyncio.create_task(self._listen_openai())

        # 1. VAD aus → Begrüßung nicht unterbrechbar
        await self._sync_session(disable_vad=True)

        # 2. Verbatim-Greeting via response.create Override
        await self.send_to_browser({"type": "mic_state", "text": "🔊 Aria spricht (Begrüßung — nicht unterbrechbar)"})
        await self.send_to_browser({"type": "log", "logtype": "sys", "message": "Begrüßung via Realtime (response.create override)"})
        await self._trigger_verbatim_response(REALTIME_GREETING)

        # 3. Auf Ende der Begrüßung warten (Audio drained)
        try:
            await asyncio.wait_for(self._wait_for_response_and_playback_done(), timeout=20)
        except asyncio.TimeoutError:
            await self.send_to_browser({"type": "log", "logtype": "err", "message": "Begrüßung-Timeout (20s)"})

        if self.session.mode == "ended":
            return

        # 4. Buffer leeren + VAD an → normales Gespräch
        await self._openai_send({"type": "input_audio_buffer.clear"})
        await self._sync_session(disable_vad=False)
        await self.send_to_browser({
            "type": "mic_state",
            "text": "🎙️ Höre zu... (sprich einfach, du kannst Aria jederzeit unterbrechen)",
        })

    # ─── Session Update an OpenAI Realtime ─────────────────────────────
    async def _sync_session(self, disable_vad: bool = False):
        if not self.openai_ws:
            return
        silence_ms = 3000 if self.session.mode == "interview" else 1500
        turn_detection = (
            None if disable_vad
            else {
                "type": "server_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": silence_ms,
            }
        )
        instructions = build_system_prompt(self.session, self.data)
        active_tools = tools_for_mode(self.session.mode)
        session_config = {
            "modalities": ["text", "audio"],
            "instructions": instructions,
            "voice": self.session.openai_voice,
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "input_audio_transcription": {"model": "gpt-4o-transcribe", "language": "de"},
            "turn_detection": turn_detection,
            "tools": active_tools,
            "tool_choice": "auto",
            "temperature": 0.8,
        }
        await self._openai_send({"type": "session.update", "session": session_config})
        vad_info = "VAD AUS (nicht unterbrechbar)" if disable_vad else f"silence={silence_ms}ms"
        tool_names = ", ".join(t["name"] for t in active_tools) or "(keine)"
        await self.send_to_browser({
            "type": "log", "logtype": "sys",
            "message": f"Realtime session aktualisiert (mode={self.session.mode}, {vad_info}, tools=[{tool_names}], instructions={len(instructions)} chars)",
        })

    # ─── Verbatim-Response (response.create mit Override) ──────────────
    async def _trigger_verbatim_response(self, text: str):
        if not self.openai_ws:
            return
        # Anchor-System-Message in der Conversation
        await self._openai_send({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "system",
                "content": [{"type": "input_text", "text": "[Sprich jetzt den vorgegebenen Text aus.]"}],
            },
        })
        # Response mit fokussiertem Override (keine Tools, niedrige Temp)
        await self._openai_send({
            "type": "response.create",
            "response": {
                "modalities": ["text", "audio"],
                "instructions": (
                    "Sprich JETZT exakt folgenden Text aus, WORTWÖRTLICH und VOLLSTÄNDIG, in genau dieser "
                    f"Wortwahl und Reihenfolge:\n\n{text}\n\n"
                    "WICHTIG: Keine Auslassungen, keine Umformulierungen, keine Zusätze. "
                    "Inklusive der Schlussfrage am Ende. Sprich diesen Text und nichts anderes."
                ),
                "tool_choice": "none",
                "temperature": 0.7,
            },
        })

    # ─── Wait-Pattern: response.done + Browser-Playback-Drain ──────────
    async def _wait_for_response_and_playback_done(self):
        self._response_done_event.clear()
        self._playback_drained_event.clear()
        await self._response_done_event.wait()
        # Browser signalisieren, dass keine weiteren Audio-Chunks mehr kommen
        await self.send_to_browser({"type": "agent_audio_end"})
        try:
            await asyncio.wait_for(self._playback_drained_event.wait(), timeout=10)
        except asyncio.TimeoutError:
            await self.send_to_browser({
                "type": "log", "logtype": "sys",
                "message": "Playback-Drain Timeout — fortfahren",
            })

    # ─── OpenAI → Bridge (Event-Listener) ──────────────────────────────
    async def _listen_openai(self):
        try:
            async for raw in self.openai_ws:
                event = json.loads(raw)
                await self._handle_openai_event(event)
        except websockets.exceptions.ConnectionClosed:
            await self.send_to_browser({"type": "log", "logtype": "sys", "message": "Realtime WS geschlossen"})
        except Exception as e:
            await self.send_to_browser({"type": "log", "logtype": "err", "message": f"OpenAI listen Fehler: {e}"})

    async def _handle_openai_event(self, event: dict):
        et = event.get("type")

        if et == "session.created":
            await self.send_to_browser({"type": "log", "logtype": "sys", "message": "Realtime session.created"})

        elif et == "input_audio_buffer.speech_started":
            await self.send_to_browser({"type": "log", "logtype": "vad", "message": "🟢 User-Sprache erkannt (server VAD)"})
            await self.send_to_browser({"type": "mic_state", "text": "🔴 Du sprichst..."})
            # Barge-In: Browser-Playback stoppen + laufende Response abbrechen
            await self.send_to_browser({"type": "stop_playback"})
            await self._openai_send({"type": "response.cancel"})

        elif et == "input_audio_buffer.speech_stopped":
            await self.send_to_browser({"type": "log", "logtype": "vad", "message": "🔴 User-Sprache vorbei"})
            await self.send_to_browser({"type": "mic_state", "text": "⏳ Verarbeite..."})

        elif et == "conversation.item.input_audio_transcription.completed":
            transcript = event.get("transcript", "") or ""
            await self.send_to_browser({"type": "log", "logtype": "stt", "message": f'User: "{transcript}"'})
            await self.send_to_browser({"type": "transcript_user", "text": transcript})
            if self.session.mode == "interview" and transcript.strip():
                self.session.current_answer_buffer.append(transcript)
                await self.send_to_browser({
                    "type": "log", "logtype": "sys",
                    "message": f"Antwort-Buffer für Frage {self.session.current_question_idx + 1}: "
                               f"{len(self.session.current_answer_buffer)} Teil(e)",
                })

        elif et == "response.audio.delta":
            delta = event.get("delta")
            if delta:
                await self.send_to_browser({"type": "agent_audio", "data": delta})

        elif et == "response.audio_transcript.done":
            transcript = event.get("transcript", "") or ""
            if transcript:
                self.session.last_agent_message = transcript
                await self.send_to_browser({"type": "log", "logtype": "llm", "message": f'Aria: "{transcript}"'})
                await self.send_to_browser({"type": "transcript_agent", "text": transcript})

        elif et == "response.function_call_arguments.done":
            await self._handle_function_call(event)

        elif et == "response.done":
            self._response_done_event.set()
            if self.pending_continuation:
                self.pending_continuation = False
                await self.send_to_browser({"type": "log", "logtype": "sys", "message": "Trigger Continuation-Response (nach Tool-Calls)"})
                await self._openai_send({"type": "response.create"})

        elif et == "error":
            err = event.get("error", {}) or {}
            err_msg = err.get("message") or json.dumps(err, ensure_ascii=False)
            await self.send_to_browser({"type": "log", "logtype": "err", "message": f"Realtime-Fehler: {err_msg}"})

    # ─── Function-Call-Handling ────────────────────────────────────────
    async def _handle_function_call(self, event: dict):
        call_id = event.get("call_id")
        name = event.get("name")
        try:
            args = json.loads(event.get("arguments") or "{}")
        except Exception:
            args = {}

        ctx = ToolContext(
            session=self.session,
            data=self.data,
            on_event=self.send_to_browser,
            email_service=self.email_service,
            score_candidate_fn=lambda: score_candidate(self.session, self.data, self.send_to_browser),
            end_call_with_escalation_fn=lambda reason: self._schedule_human_handoff(reason),
        )

        try:
            result = await execute_tool(name, args, ctx)
        except Exception as e:
            result = {"error": f"Tool execution failed: {e}"}
            await self.send_to_browser({"type": "log", "logtype": "err", "message": f"Tool {name} crashed: {e}"})

        # Tool-Result an OpenAI zurück
        await self._openai_send({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(result, ensure_ascii=False),
            },
        })

        # Session aktualisieren (mode/question_idx kann sich geändert haben)
        await self._sync_session(disable_vad=False)

        if name == "escalate_to_human":
            # Eigener Handoff-Flow (verbatim Übergangstext + endCall) — keine Auto-Continuation
            asyncio.create_task(self._schedule_human_handoff(args.get("reason", "")))
        else:
            self.pending_continuation = True

    # ─── Mensch-Übergabe (asynchron) ───────────────────────────────────
    async def _schedule_human_handoff(self, reason: str):
        # Laufende LLM-Ausgabe kappen (gleicher Pattern wie CV-Upload).
        # Auf response.done zu warten würde racen, weil das Event durch die
        # tool-Antwort meist schon gesetzt ist, bevor dieser Task startet.
        await self._openai_send({"type": "response.cancel"})
        await self.send_to_browser({"type": "stop_playback"})
        await asyncio.sleep(0.2)
        await self.send_to_browser({"type": "log", "logtype": "sys", "message": "Spreche Übergangs-Ansage"})
        await self._trigger_verbatim_response(HUMAN_HANDOFF_MESSAGE)
        try:
            await asyncio.wait_for(self._wait_for_response_and_playback_done(), timeout=20)
        except asyncio.TimeoutError:
            pass
        await asyncio.sleep(0.4)
        await self.send_to_browser({"type": "log", "logtype": "sys", "message": f"Call wird beendet (Eskalation: {reason})"})
        await self._end_call()

    # ─── CV-Upload-Flow ────────────────────────────────────────────────
    async def _handle_cv_upload(self, msg: dict):
        filename = msg.get("filename", "cv.pdf")
        cv_base64 = msg.get("data", "")
        self.session.cv_base64 = cv_base64

        await self.send_to_browser({"type": "system_message", "text": f"📎 Lebenslauf hochgeladen: {filename}"})
        await self.send_to_browser({"type": "log", "logtype": "sys", "message": f"Lebenslauf hochgeladen: {filename}"})

        self.session.mode = "cv_received"
        await self.send_to_browser({"type": "state_update", "state": self.session.to_dashboard_dict(self.data)})
        await self.send_to_browser({"type": "status", "text": "Lebenslauf empfangen, generiere Fragen...", "className": "active"})
        await self.send_to_browser({"type": "log", "logtype": "sys", "message": "CV-Upload-Flow"})

        # Aktuellen Smalltalk stoppen
        await self._openai_send({"type": "response.cancel"})
        await self.send_to_browser({"type": "stop_playback"})

        # Bestätigung anstoßen
        await self._sync_session(disable_vad=False)
        await self._openai_send({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "system",
                "content": [{"type": "input_text", "text": (
                    "[Der Bewerber hat gerade seinen Lebenslauf hochgeladen. Bestätige knapp und natürlich "
                    '(z.B. "Super, hab ihn bekommen, ich überlege mir gleich ein paar passende Fragen"). '
                    "1-2 Sätze. Stelle KEINE Fragen, warte auf das nächste System-Signal.]"
                )}],
            },
        })
        await self._openai_send({"type": "response.create"})

        # Parallel: Fragen via Claude
        try:
            questions = await generate_questions_from_cv(self.session, self.data, self.send_to_browser)
            self.session.questions = questions
            await self.send_to_browser({
                "type": "log", "logtype": "sys",
                "message": f"Fragen-Generierung fertig: {len(questions)} Fragen",
            })

            self.session.mode = "interview"
            self.session.current_question_idx = 0
            await self.send_to_browser({"type": "state_update", "state": self.session.to_dashboard_dict(self.data)})
            await self.send_to_browser({"type": "status", "text": "Interview", "className": "active"})

            await self._sync_session(disable_vad=False)
            await self._openai_send({
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "system",
                    "content": [{"type": "input_text", "text": (
                        "[Lebenslauf wurde verarbeitet, Fragen sind bereit. Stelle JETZT die erste Interview-Frage "
                        "natürlich und kurz. Die Frage steht in deinen Instructions oben. Rufe noch KEIN record_answer "
                        "auf — der Bewerber hat noch nicht geantwortet.]"
                    )}],
                },
            })
            await self._openai_send({"type": "response.create"})
        except Exception as e:
            await self.send_to_browser({"type": "log", "logtype": "err", "message": f"Upload-Flow: {e}"})
            await self.send_to_browser({"type": "status", "text": "Fehler bei Fragen-Generierung", "className": "error"})
            await self._openai_send({
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "system",
                    "content": [{"type": "input_text", "text": (
                        "[Es gab einen Fehler bei der Fragen-Generierung. Entschuldige dich beim Bewerber und "
                        "biete an, ihn an einen Menschen weiterzuleiten.]"
                    )}],
                },
            })
            await self._openai_send({"type": "response.create"})

    # ─── Call-Ende + Cleanup ───────────────────────────────────────────
    async def _end_call(self):
        if self.session.mode in ("idle", "ended"):
            return
        self.session.mode = "ended"
        await self.send_to_browser({"type": "system_message", "text": "— Call beendet —"})
        await self.send_to_browser({"type": "log", "logtype": "sys", "message": "=== Call beendet ==="})
        await self.send_to_browser({"type": "call_ended"})
        await self.send_to_browser({"type": "state_update", "state": self.session.to_dashboard_dict(self.data)})
        await self.send_to_browser({"type": "status", "text": "Call beendet", "className": ""})
        await self._cleanup()

    async def _cleanup(self):
        if self.openai_listener_task:
            self.openai_listener_task.cancel()
            self.openai_listener_task = None
        if self.openai_ws:
            try:
                await self.openai_ws.close()
            except Exception:
                pass
            self.openai_ws = None

    # ─── Helpers ────────────────────────────────────────────────────────
    async def _openai_send(self, msg: dict):
        if not self.openai_ws:
            return
        try:
            await self.openai_ws.send(json.dumps(msg, ensure_ascii=False))
        except Exception as e:
            await self.send_to_browser({"type": "log", "logtype": "err", "message": f"OpenAI send Fehler: {e}"})

    async def send_to_browser(self, msg: dict):
        """Robust: Disconnects schweigend ignorieren."""
        try:
            await self.browser_ws.send_text(json.dumps(msg, ensure_ascii=False))
        except Exception:
            pass

    async def _safe_send_browser(self, msg: dict):
        await self.send_to_browser(msg)
