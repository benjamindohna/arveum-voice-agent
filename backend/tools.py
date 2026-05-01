"""Tool-Definitionen + Handler.

Format: für OpenAI Realtime API → 'function'-Type mit parameters JSON Schema.
Job-Lookups gehen gegen voice.arveum.ai (siehe `voice_api.py`)."""

from typing import Any, Callable, Awaitable

import voice_api


# Tool-Definitionen im OpenAI Realtime Format
TOOL_DEFS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "list_open_jobs",
        "description": "Listet alle aktuell offenen Stellen auf. Verwende dies, wenn der Anrufer nach offenen Stellen, Vakanzen, Bewerbungsmöglichkeiten o.ä. fragt.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "type": "function",
        "name": "get_job_details",
        "description": "Liefert detaillierte Informationen zu einer bestimmten Stelle (Beschreibung, Anforderungen, Standort). Verwende dies, wenn der Anrufer mehr über eine konkrete Rolle wissen möchte.",
        "parameters": {
            "type": "object",
            "properties": {"job_id": {"type": "string", "description": "ID der Stelle aus list_open_jobs, z.B. JOB007"}},
            "required": ["job_id"],
        },
    },
    {
        "type": "function",
        "name": "send_upload_link",
        "description": "Sendet dem Bewerber einen Email-Link zum Hochladen seines Lebenslaufs. Aufrufen NUR nachdem der Bewerber: (1) eine konkrete Rolle gewählt hat, (2) sie bestätigt hat, (3) das 15-Min-Commitment akzeptiert hat. Nach diesem Tool-Call beendet der Free Mode und der Apply Mode beginnt — keine Nebenfragen mehr beantworten.",
        "parameters": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Email-Adresse des Bewerbers"},
                "job_id": {"type": "string", "description": "ID der gewählten Rolle aus list_open_jobs"},
            },
            "required": ["email", "job_id"],
        },
    },
    {
        "type": "function",
        "name": "escalate_to_human",
        "description": "Beendet den KI-Call und vermittelt an einen menschlichen Recruiter. SOFORT aufrufen, wenn der Anrufer 'Mensch', 'echter Recruiter', 'jemand anderes' o.ä. signalisiert.",
        "parameters": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
    {
        "type": "function",
        "name": "record_answer",
        "description": "NUR aufrufen, wenn der Bewerber die aktuelle Frage VOLLSTÄNDIG beantwortet hat. Erhöht den Frage-Index. NICHT aufrufen wenn: (a) Bewerber off-topic redet, (b) noch keine Antwort kam, (c) Bewerber eine Klärungsfrage stellt, (d) du dir UNSICHER bist ob die Antwort vollständig ist — in dem Fall frage stattdessen 'Möchtest du noch etwas ergänzen?' und warte. Bewerber pausieren oft mid-thought 3-5 Sekunden, das ist KEIN Ende. Im Zweifel lieber nachfragen als prematur committen.",
        "parameters": {
            "type": "object",
            "properties": {
                "answer_summary": {"type": "string", "description": "Kurze Zusammenfassung der Antwort (1-2 Sätze, für Recruiter-Auswertung). Fasse den GANZEN Antwort-Inhalt zusammen, nicht nur den letzten Satz."},
            },
            "required": ["answer_summary"],
        },
    },
    {
        "type": "function",
        "name": "extend_previous_answer",
        "description": "Aufrufen, wenn der Bewerber inhaltlich klar die VORHERIGE Frage weiter beantwortet (Fortsetzung), obwohl du bereits record_answer aufgerufen hast und der Index bereits weitergesprungen ist. Das hängt die neue User-Eingabe an die zuletzt registrierte Antwort an, OHNE den Index zu verändern.",
        "parameters": {
            "type": "object",
            "properties": {
                "additional_summary": {"type": "string", "description": "Was der Bewerber zur vorherigen Antwort ergänzt hat (1 Satz)."},
            },
            "required": ["additional_summary"],
        },
    },
]


# Mode → erlaubte Tool-Namen. Nur diese werden an die LLM exponiert,
# damit Cross-Mode-Halluzinationen (z.B. record_answer im Free Mode)
# unmöglich sind statt nur durch Prompt-Regeln verboten.
_FREE_TOOLS = {
    "list_open_jobs",
    "get_job_details",
    "send_upload_link",
    "escalate_to_human",
}
_INTERVIEW_TOOLS = {
    "record_answer",
    "extend_previous_answer",
    "escalate_to_human",
}
_MIN_TOOLS = {"escalate_to_human"}


def tools_for_mode(mode: str) -> list[dict[str, Any]]:
    """Tools, die der LLM im gegebenen Session-Mode aufrufen darf."""
    if mode == "interview":
        allowed = _INTERVIEW_TOOLS
    elif mode == "free":
        allowed = _FREE_TOOLS
    elif mode in ("awaiting_upload", "cv_received", "wrapping"):
        allowed = _MIN_TOOLS
    else:
        allowed = _FREE_TOOLS
    return [t for t in TOOL_DEFS if t["name"] in allowed]


# Tool-Handler
# Signatur: async def handler(input: dict, ctx: ToolContext) -> dict
# ctx gibt Zugriff auf session, data, on_event (UI-Updates an Browser pushen),
# email_service, llm-Calls.

class ToolContext:
    """Kontext, der Tool-Handlern übergeben wird. Spart riesige Argument-Listen."""
    def __init__(self, session, on_event, email_service, score_candidate_fn, end_call_with_escalation_fn):
        self.session = session
        self.on_event = on_event                            # async Callback: dict → Browser-Event
        self.email_service = email_service
        self.score_candidate = score_candidate_fn           # async ()
        self.end_call_with_escalation = end_call_with_escalation_fn  # async (reason)


async def execute_tool(name: str, input_data: dict, ctx: ToolContext) -> dict:
    """Dispatcht den Tool-Aufruf. Rückgabe = JSON-serialisierbares Dict (geht an OpenAI als function_call_output)."""
    session = ctx.session

    await ctx.on_event({"type": "log", "logtype": "tool", "message": f"{name}({input_data})"})
    await ctx.on_event({"type": "tool_called", "name": name, "input": input_data})

    if name == "list_open_jobs":
        try:
            jobs = await voice_api.list_jobs()
            result = [
                {
                    "id": j.get("id"),
                    "title": j.get("title"),
                    "department": j.get("department"),
                    "location": j.get("location"),
                }
                for j in jobs
            ]
        except Exception as e:
            await ctx.on_event({"type": "log", "logtype": "err", "message": f"list_jobs API-Fehler: {e}"})
            result = {"error": "Stellenliste ist gerade nicht erreichbar"}

    elif name == "get_job_details":
        job_id = input_data.get("job_id", "")
        try:
            job = await voice_api.get_job_details(job_id)
            session.selected_job_data = job
            # API liefert id/title/description plus optional requirements,
            # tech_stack, benefits, kennziffer. Alles durchreichen, was da ist —
            # der Agent kann's in Free-Mode-Antworten verwenden.
            result = {k: v for k, v in job.items() if k in {
                "id", "title", "description", "department", "location",
                "type", "experience", "requirements", "tech_stack",
                "benefits", "kennziffer",
            }}
        except Exception as e:
            await ctx.on_event({"type": "log", "logtype": "err", "message": f"get_job_details API-Fehler: {e}"})
            result = {"error": f"Details zur Stelle {job_id} sind gerade nicht erreichbar"}

    elif name == "send_upload_link":
        session.caller_email = input_data["email"]
        session.selected_job_id = input_data["job_id"]
        session.mode = "awaiting_upload"
        await ctx.on_event({"type": "state_update", "state": session.to_dashboard_dict()})
        # Email-Service triggert das Browser-Modal (Mock) oder echten Versand (Resend, später)
        await ctx.email_service.send_upload_link(
            email=session.caller_email,
            job_id=session.selected_job_id,
            session=session,
            on_event=ctx.on_event,
        )
        result = {
            "status": "ok",
            "message": (
                f"Email mit Upload-Link wurde an {input_data['email']} versendet. "
                "Der Bewerber muss jetzt den Lebenslauf hochladen — sage ihm, er soll seinen "
                "Posteingang prüfen und den Anhang hochladen."
            ),
        }

    elif name == "escalate_to_human":
        # Async Übergabe-Flow: erst aktuelle Response abwarten, dann verbatim Übergangstext sprechen, dann endCall.
        session.mode = "wrapping"
        await ctx.on_event({"type": "state_update", "state": session.to_dashboard_dict()})
        await ctx.on_event({
            "type": "system_message",
            "text": f"🚪 Übergabe an menschlichen Recruiter wird vorbereitet — Grund: {input_data.get('reason', '')}",
        })
        await ctx.on_event({"type": "status", "text": "Übergabe an Mensch...", "className": "active"})
        # Den eigentlichen Handoff-Flow startet voice_bridge selbst, wenn es 'escalate_to_human' sieht
        result = {
            "status": "acknowledged",
            "message": "Übergabe wird gleich sprachlich angekündigt und der Call dann beendet. Sage selbst nichts mehr.",
        }

    elif name == "record_answer":
        if session.mode != "interview":
            result = {"error": "record_answer nur im Interview-Mode erlaubt"}
        else:
            recorded_q = session.questions[session.current_question_idx]
            full_answer = " ".join(session.current_answer_buffer) if session.current_answer_buffer else "(keine Transkription)"
            session.answers.append({
                "question": recorded_q,
                "answer_summary": input_data["answer_summary"],
                "answer_full": full_answer,
                "parts": len(session.current_answer_buffer),
            })
            await ctx.on_event({
                "type": "log",
                "logtype": "sys",
                "message": f"✓ Frage {session.current_question_idx + 1}/{len(session.questions)} committed",
                "data": {"summary": input_data["answer_summary"], "parts": len(session.current_answer_buffer)},
            })
            session.current_answer_buffer = []
            session.current_question_idx += 1
            await ctx.on_event({"type": "state_update", "state": session.to_dashboard_dict()})

            if session.current_question_idx >= len(session.questions):
                session.mode = "wrapping"
                await ctx.on_event({"type": "log", "logtype": "sys", "message": "Alle Fragen durch — wechsle zu Wrapping"})
                # Score läuft im Hintergrund, parallel zum Wrap-Up des Agents
                await ctx.score_candidate()
                result = {
                    "status": "recorded",
                    "mode": "wrapping",
                    "message": "Alle Fragen beantwortet. Bedanke dich kurz und beende das Interview.",
                }
            else:
                result = {
                    "status": "recorded",
                    "next_question_idx": session.current_question_idx + 1,
                    "next_question_total": len(session.questions),
                    "message": "Antwort wurde gespeichert. Stelle jetzt die nächste Frage.",
                }

    elif name == "extend_previous_answer":
        if not session.answers:
            result = {"error": "Keine vorherige Antwort vorhanden, die ergänzt werden könnte"}
        else:
            prev = session.answers[-1]
            additional_text = " ".join(session.current_answer_buffer)
            prev["answer_summary"] += f" [Ergänzung: {input_data['additional_summary']}]"
            prev["answer_full"] += " " + additional_text
            prev["parts"] = prev.get("parts", 1) + len(session.current_answer_buffer)
            await ctx.on_event({
                "type": "log",
                "logtype": "sys",
                "message": f"↺ Vorherige Antwort retroaktiv ergänzt (Frage {len(session.answers)})",
                "data": {"added_summary": input_data["additional_summary"]},
            })
            session.current_answer_buffer = []
            await ctx.on_event({"type": "state_update", "state": session.to_dashboard_dict()})
            result = {
                "status": "extended",
                "message": "Ergänzung wurde an die vorherige Antwort angehängt. Der Frage-Index bleibt unverändert. Stelle jetzt erneut die aktuelle Frage, oder warte auf eine neue Antwort.",
            }

    else:
        result = {"error": "Unbekanntes Tool"}

    # Result loggen
    import json as _json
    preview = _json.dumps(result, ensure_ascii=False)[:200]
    await ctx.on_event({"type": "log", "logtype": "tool", "message": f"{name} → result", "data": preview})
    return result
