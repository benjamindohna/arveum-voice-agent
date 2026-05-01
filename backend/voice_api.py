"""HTTP-Client für voice.arveum.ai Endpoints.

Aktuell nur Jobs (`/api/jobs`, `/api/jobs/details`). Weitere Endpoints
(`/api/candidate/*`) kommen schrittweise.
"""

import os
from typing import Any

import httpx


def _base_url() -> str:
    return os.environ.get("VOICE_BACKEND_URL", "https://voice.arveum.ai").rstrip("/")


async def list_jobs(department: str | None = None) -> list[dict[str, Any]]:
    """`POST /api/jobs` — gibt Liste offener Stellen zurück.

    Response-Schema (aus voice.arveum.ai):
    `{ count, departments, jobs: [{id, title, department, location, type, experience}] }`
    """
    payload: dict[str, Any] = {}
    if department:
        payload["department"] = department
    async with httpx.AsyncClient(timeout=4.0) as client:
        response = await client.post(f"{_base_url()}/api/jobs", json=payload)
        response.raise_for_status()
        return response.json().get("jobs", [])


async def get_job_details(job_id: str) -> dict[str, Any]:
    """`POST /api/jobs/details` — gibt Volltext-Details zur Stelle zurück.

    Response-Schema: `{id, title, description, ...}`. `description` ist Freitext.
    """
    async with httpx.AsyncClient(timeout=4.0) as client:
        response = await client.post(
            f"{_base_url()}/api/jobs/details",
            json={"job_id": job_id},
        )
        response.raise_for_status()
        return response.json()


async def get_company_info() -> dict[str, Any]:
    """`POST /api/company` — Profil des Mandanten (Name, Tagline, Beschreibung, Kultur, Founders).

    Liefert KEINE konkreten HR-Policies (Urlaubstage, Gehalt, Homeoffice-Regelung etc.) —
    dafür gibt es derzeit keinen Endpoint."""
    async with httpx.AsyncClient(timeout=4.0) as client:
        response = await client.post(f"{_base_url()}/api/company", json={})
        response.raise_for_status()
        return response.json()
