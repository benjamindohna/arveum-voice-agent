"""Job-Enrichment: leitet `application_focus` automatisch aus der Description ab.

voice.arveum.ai liefert Stellen als `{id, title, description}` (Freitext).
Für die Question-Generation und das Scoring brauchen wir aber eine fokussierte
Aussage, was der Bewerber bei dieser Rolle besonders unter Beweis stellen soll
(Original-Feld: `application_focus`). Das leiten wir einmalig pro Stelle aus
der Description ab, gecached in-memory bis zum Restart (Phase B: SQLite).
"""

import os
from typing import Awaitable, Callable

import anthropic


_client: anthropic.AsyncAnthropic | None = None
_focus_cache: dict[str, str] = {}


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY nicht gesetzt")
        _client = anthropic.AsyncAnthropic(api_key=api_key)
    return _client


async def derive_application_focus(
    job_id: str,
    title: str,
    description: str,
    model: str,
    on_event: Callable[[dict], Awaitable[None]] | None = None,
) -> str:
    """Gibt einen 1-2-Satz-Fokus für das Interview zurück, gecached pro job_id."""
    if job_id in _focus_cache:
        return _focus_cache[job_id]

    user_prompt = (
        f'Lies die Stellenbeschreibung für "{title}" und formuliere in 1-2 Sätzen, '
        "worauf das Interview den Schwerpunkt legen sollte. Konkret: welche Fähigkeiten, "
        "Erfahrungen oder Eigenschaften sind kritisch — was sollte ein Recruiter bei "
        "dieser Rolle besonders prüfen?\n\n"
        "Antworte nur mit dem Fokus-Satz, ohne Vorrede.\n\n"
        f"Stellenbeschreibung:\n{description}"
    )

    if on_event:
        await on_event({
            "type": "log", "logtype": "llm",
            "message": f"Anthropic → {model} (Application-Focus für {job_id})",
        })

    try:
        client = _get_client()
        response = await client.messages.create(
            model=model,
            max_tokens=300,
            messages=[{"role": "user", "content": user_prompt}],
        )
        focus = next((b.text for b in response.content if b.type == "text"), "").strip()
        if not focus:
            focus = "Allgemeine fachliche Eignung und Cultural Fit für die Rolle."
        _focus_cache[job_id] = focus
        return focus
    except Exception as e:
        if on_event:
            await on_event({
                "type": "log", "logtype": "err",
                "message": f"Application-Focus-Ableitung fehlgeschlagen: {e}",
            })
        # Fallback: generischer Fokus, damit Question-Gen weiterläuft
        return "Allgemeine fachliche Eignung und Cultural Fit für die Rolle."
