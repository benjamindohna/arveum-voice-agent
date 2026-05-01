"""Anthropic Claude für Backend-Tasks: Question-Generation aus PDF + Scoring.

Realtime-API kann keine PDFs lesen, daher bleibt Claude für diese zwei Tasks zuständig.
1:1 Port aus mvp-call-agent/app.js generateQuestionsFromCv + scoreCandidate."""

import os
import json
import re
import asyncio
import anthropic


_client = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY nicht gesetzt")
        _client = anthropic.AsyncAnthropic(api_key=api_key)
    return _client


def _strip_markdown_fences(text: str) -> str:
    cleaned = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


async def generate_questions_from_cv(session, data, on_event) -> list[str]:
    """Analysiert CV (base64 PDF) für gewählte Stelle, gibt N Interview-Fragen zurück."""
    job = next((j for j in data["jobs"] if j["id"] == session.selected_job_id), None)
    if job is None:
        raise RuntimeError(f"Stelle {session.selected_job_id} nicht gefunden")
    n = session.question_count or 8

    prompt_text = f"""Analysiere diesen Lebenslauf für die Stelle "{job['title']}" bei AlmaCare.

Stellen-Fokus: {job['application_focus']}
Anforderungen: {'; '.join(job['requirements'])}
Nice-to-have: {'; '.join(job['nice_to_have'])}

Erstelle GENAU {n} tiefgehende, rollenspezifische Fragen, die folgendes prüfen:
- Fachliche Substanz (für Pflegerollen: konkrete Praxis-Situationen, nicht abstrakte Theorie)
- Behavioral / konkrete Beispiele aus der Vergangenheit
- Motivation und Cultural Fit zu AlmaCare
{"- Mindestens eine Frage zu schwierigen Situationen (Konflikte, Belastung)" if n >= 4 else ""}

Antworte AUSSCHLIESSLICH mit einem JSON-Array von {n} Strings (die Fragen), sonst nichts. Keine Markdown-Codeblöcke, kein Vorwort."""

    system = (
        "Du bist ein erfahrener Recruiting-Experte. Du erstellst gezielte Interview-Fragen, "
        "die echtes fachliches Know-how von oberflächlichen Antworten unterscheiden. "
        "Antworte ausschließlich mit dem geforderten JSON-Array."
    )

    await on_event({
        "type": "log",
        "logtype": "llm",
        "message": f"Anthropic → {session.backend_llm_model} (Question-Gen)",
        "data": {"questions_target": n},
    })

    client = _get_client()
    response = await client.messages.create(
        model=session.backend_llm_model,
        max_tokens=2048,
        system=system,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": session.cv_base64,
                    },
                },
                {"type": "text", "text": prompt_text},
            ],
        }],
    )
    text = next((b.text for b in response.content if b.type == "text"), "").strip()
    cleaned = _strip_markdown_fences(text)
    questions = json.loads(cleaned)

    await on_event({
        "type": "log",
        "logtype": "sys",
        "message": f"{len(questions)} Fragen generiert",
        "data": " | ".join(f"{i + 1}. {q[:80]}" for i, q in enumerate(questions)),
    })
    return questions


async def score_candidate(session, data, on_event) -> dict:
    """Bewertet die gesammelten Antworten. Gibt {score, highlights} zurück."""
    job = next((j for j in data["jobs"] if j["id"] == session.selected_job_id), None)
    if job is None:
        raise RuntimeError(f"Stelle {session.selected_job_id} nicht gefunden")

    answers_block = "\n\n".join(
        f"Frage {i + 1}: {a['question']}\n"
        f"Antwort (volltext): {a.get('answer_full') or '(kein Volltext)'}\n"
        f"Zusammenfassung: {a.get('answer_summary') or '(keine)'}"
        for i, a in enumerate(session.answers)
    )

    user_prompt = f"""Du bist ein erfahrener Recruiter bei AlmaCare. Bewerte diesen Bewerber für die Stelle "{job['title']}" basierend auf dem Interview.

Interview-Antworten:
{answers_block}

Gib zurück ein JSON-Objekt mit:
- score (0-100, integer)
- highlights (Array aus 3-5 kurzen Bullet-Strings: was war stark, was war schwach)

Antworte NUR mit dem JSON-Objekt."""

    system = "Du bist ein erfahrener Recruiter. Antworte nur mit dem geforderten JSON-Objekt."

    await on_event({
        "type": "log",
        "logtype": "llm",
        "message": f"Anthropic → {session.backend_llm_model} (Scoring)",
    })

    try:
        client = _get_client()
        response = await client.messages.create(
            model=session.backend_llm_model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "").strip()
        cleaned = _strip_markdown_fences(text)
        result = json.loads(cleaned)
        session.score = result.get("score")
        session.highlights = result.get("highlights", [])
        await on_event({
            "type": "log",
            "logtype": "sys",
            "message": f"Scoring: {session.score}/100",
            "data": " | ".join(session.highlights),
        })
        await on_event({"type": "state_update", "state": session.to_dashboard_dict(data)})
        return result
    except Exception as e:
        await on_event({
            "type": "log",
            "logtype": "err",
            "message": f"Scoring fehlgeschlagen: {e}",
        })
        session.score = "?"
        await on_event({"type": "state_update", "state": session.to_dashboard_dict(data)})
        return {"score": "?", "highlights": []}
