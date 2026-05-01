# 05 — Production-Architecture-Plan

Wie wir vom Browser-MVP (aktueller `realtime-only`-Branch) zu einer produktiv hostbaren Multi-Tenant-Lösung kommen.

## Empfohlene Ziel-Architektur

**Browser-heavy SPA + schlanker Backend-Server. Beide in TypeScript.**

```
┌──────────────────────────────────┐         ┌────────────────────────────────────────┐
│  BROWSER (Frontend, TS+React)    │         │  BACKEND (Node.js + TypeScript)        │
│                                  │         │                                        │
│  • UI                            │ ◄──HTTPS──┤ /api/auth/*                          │
│  • Voice-Pipeline                │         │ /api/companies/*                       │
│    - Realtime WebSocket          │         │ /api/calls/*                           │
│    - Mic-Capture (PCM16)         │         │ /api/cv-uploads/*                      │
│    - Audio-Wiedergabe            │         │ /api/dashboard/*                       │
│  • Recruiter-Dashboard           │ ◄──WSS────┤ /ws/realtime-bridge   (proxy)        │
│  • Live-Log                      │         │                                        │
│                                  │         │ ┌──────────────────────────────────┐  │
└──────────────┬───────────────────┘         │ │ Externe Dienste                  │  │
               │                              │ │  ├─ OpenAI Realtime API           │  │
               │                              │ │  ├─ Anthropic Claude API          │  │
               ▼                              │ │  ├─ Resend (Email)                │  │
        Bewerber-Email-Link                   │ │  └─ Postgres + S3                 │  │
        ─────────────►                        │ └──────────────────────────────────┘  │
                                              │                                        │
                                              └────────────────────────────────────────┘
```

## Warum nicht vollständig Server-side Voice?

**Server-side Voice (Python + Pipecat / LiveKit Agents)** ist die nächste Evolutionsstufe. Erst sinnvoll, wenn ihr braucht:
- Echte Telefonnummern (Twilio-Integration)
- Multi-hundert parallele Calls über zentrale Server-Pools
- Server-seitige Recording mit forensischer Compliance
- Telefonie-spezifische Features (Anrufweiterleitung, IVR-Menüs)

Bis dahin reicht der Browser-Voice-Pfad. Migration zu Server-side Voice ist ein klar abgegrenztes Phase-2-Projekt — kein Argument gegen den jetzigen Weg.

## Sprach-Entscheidung: TypeScript überall

| Argument | Pro TS |
|---|---|
| Code-Größe wächst | Bei ~1300 Zeilen ist plain JS schon riskant. Bei 10k+ wird's gefährlich ohne Types. |
| Frontend ↔ Backend | Beide Seiten teilen Tool-Schemas, API-Contracts, Mock-Daten-Typen. Mit TS einmal definieren, überall nutzen. |
| Hiring | TypeScript-Devs sind häufiger und günstiger als Python-Devs mit Voice-Erfahrung. |
| AI-Code-Generation | Modelle wie Claude/Cursor produzieren bessere TS-Output mit Types als untyped JS. |
| Refactoring | Renames + Schema-Änderungen sind in TS sicher; in plain JS Russisches Roulette. |

**Konsequenz**: Frontend wird (in Phase 1) auf TypeScript migriert. Backend ist von Anfang an TypeScript.

## Phasen-Plan

### Phase 0 — Heute (realtime-only)
✅ Browser-MVP mit Realtime API
✅ Mock-Daten in JSON
✅ Lokales Testing via `python -m http.server`
❌ API-Keys im Browser → nicht produktionsfähig
❌ Email-Modal ist Simulation
❌ Keine echte Datenbank
❌ Single-User, keine Auth

### Phase 1 — MVP-Production (≈ 2-3 Wochen)

**Ziel**: erste echten Pilot-Kunden können nutzen.

**Backend (neu, Node.js + TypeScript + Hono):**
- `POST /api/auth/login` (Magic Link via Email)
- `GET /api/companies/me` — Firma + Konfiguration
- `POST /api/calls` — neuen Call starten, gibt ephemeral Realtime-Token zurück
- `POST /api/cv-uploads/init` — gibt signed S3-Upload-URL zurück
- `POST /api/cv-uploads/complete` — Webhook-Endpoint nach Upload
- `GET /api/dashboard/calls` — Recruiter-Dashboard-Daten

**Frontend-Änderungen:**
- TypeScript-Migration (`app.js` → `app.ts`, `realtime.js` → `realtime.ts`)
- Optional: Vue/React/Svelte-Migration für UI-Komponenten (separates Stretch-Goal)
- API-Calls statt direkter OpenAI/Anthropic-Calls
- Login-Screen
- Multi-Company-Switching
- Echte Email-Link-Wartelogik (statt Modal)

**Infra:**
- Postgres (Neon/Supabase): Companies, Users, Calls, Bewerber, Scores, CV-Metadata
- S3-kompatibel (AWS / R2 / Backblaze): CVs, Recordings, Transcripts
- Resend / Postmark: echter Email-Versand
- Vercel/Netlify: Frontend
- Railway/Fly.io/Render: Backend
- Sentry: Error-Tracking
- PostHog: Product-Analytics

**Was wegfällt** vs. heute:
- Mock-Daten (wandern in Postgres je Mandant)
- localStorage für API-Keys
- Test-CV-PDF (wird durch Sample-Daten in DB ersetzt)

### Phase 2 — Skalierung & Telefonie (≈ 1-2 Monate je nach Scope)

**Ziel**: echte Telefonnummern, Multi-Tenancy in Production.

**Hinzukommt:**
- Twilio + Pipecat-Bridge (Python-Komponente!) — echte 0800-Nummern
- Voice-Logik wandert teilweise nach Server-side (Python + Pipecat)
- Browser-Voice bleibt als "Web-Embed"-Variante für Karriereseiten
- Admin-UI: Firmen onboarden, Stellen pflegen, Benefits einstellen
- Analytics-Dashboard für Recruiter (Conversion-Funnel etc.)
- A/B-Testing-Framework für Prompts

**Compliance-Hardening:**
- DSGVO: Lösch-Endpoint pro Bewerber, Audit-Log
- EU AI Act: Risiko-Register, Bias-Audit-Pipeline (Quartalsweise)
- ISO 27001-Vorbereitung

### Phase 3 — ATS-Integrationen + Self-Serve (≈ 2-3 Monate)

- Personio / Greenhouse / Lever / Workday / SAP SuccessFactors API-Integrationen
- Self-Serve-Onboarding (Firma kann sich selbst registrieren + konfigurieren)
- Pricing-Tiers + Stripe-Integration
- Webhooks für Customer-Backend-Hooks
- Native Mobile App? (eher Phase 4)

## Konkreter erster Schritt

Sobald Phase-1-Tickets aufgesetzt sind, würde ich **Backend zuerst** in dieser Reihenfolge bauen:

1. **Repository-Setup**: Monorepo (`apps/frontend`, `apps/backend`, `packages/shared`) mit pnpm workspaces oder Turborepo
2. **Shared-Types-Package**: Tool-Schemas, Company-Schema, Call-Schema — wird von beiden Seiten importiert
3. **Backend-Skeleton**: Hono + Zod (Validation) + Drizzle (ORM) + Postgres-Connection
4. **Auth-Flow**: Email-Magic-Link
5. **Realtime-Token-Endpoint**: Backend generiert ephemeral Realtime-Tokens
6. **Frontend-Migration**: bestehender JS-Code → TS, API-Calls statt Direkt-Calls
7. **CV-Upload-Flow**: S3-Signed-URL + Resend-Email + Webhook-Empfang
8. **Postgres-Migrations + Seed-Data**: erster Test-Mandant
9. **Dashboard**: Recruiter sieht alle Calls, kann Audio anhören, Transcripts lesen
10. **Deployment**: Frontend auf Vercel, Backend auf Railway, DB auf Neon

## Was bleibt aus dem aktuellen MVP intakt

- `realtime.js`-Logik (WebSocket, AudioWorklet, Tool-Routing) ist 1:1 portierbar nach TypeScript
- Tool-Definitionen + System-Prompt-Logik aus `app.js` → wandern nahezu unverändert ins Frontend (Voice-Layer) bzw. als shared types ins shared-Package
- Mock-Daten-Schemas → werden Postgres-Tabellen
- Email-Modal-Code wird durch echten Resend-Call ersetzt (Backend), Frontend zeigt nur "Email versendet"-Bestätigung
- CV-Upload-Flow konzeptionell identisch, nur landen Bytes nicht mehr in Browser-Memory sondern in S3

Anders gesagt: **die Architektur-DNA bleibt gleich**, nur die Säulen werden professioneller.

## Tech-Stack-Vorschlag (konkret)

| Schicht | Wahl | Alternative |
|---|---|---|
| Frontend-Framework | React 19 + Vite + TypeScript | SvelteKit (kleinere Codebase) |
| UI-Lib | shadcn/ui + Tailwind | Mantine, MUI |
| Backend-Framework | Hono | Express, Fastify |
| ORM | Drizzle | Prisma |
| DB | Postgres (Neon) | Postgres (Supabase) |
| Storage | Cloudflare R2 | AWS S3 |
| Email | Resend | Postmark |
| Auth | Better-Auth oder Lucia | Clerk (managed) |
| Hosting Frontend | Vercel | Netlify, Cloudflare Pages |
| Hosting Backend | Railway | Fly.io, Render |
| Error-Tracking | Sentry | — |
| Analytics | PostHog | Mixpanel |
| CI | GitHub Actions | — |

Alle Optionen sind production-tauglich — die "Wahl"-Spalte ist meine Default-Empfehlung für Speed + DX, die "Alternative" wenn ihr spezifische Gründe habt.

## Was wir vorab klären müssen

1. **Telefonie-Vision**: nur Browser/Web-Embed, oder Telefonnummern? Beeinflusst Phase 2 stark.
2. **Multi-Tenancy-Modell**: jede Firma eigene Subdomain (`<firma>.arveum.app`) oder zentrale App mit Firmen-Switcher?
3. **Compliance-Zertifizierung**: ISO 27001 / TISAX bis wann? Beeinflusst Hosting-Wahl (EU-only zwingend) und Logging.
4. **Eigentum CV-Daten**: kunden-isoliert oder dürfen wir aggregierte Daten zum Modell-Tuning nutzen? (Datenschutz + Geschäftsmodell)
5. **Pricing-Modell**: per Call / per Hire / per Seat? Beeinflusst Backend-Quoten-Logik.

## Geschätzter Scope

- **Phase 1 mit einem erfahrenen Full-Stack-TS-Dev**: 3-4 Wochen
- **Phase 1 mit einem Mid-Level-Dev**: 6-8 Wochen
- **Phase 1 mit dir + Claude-Code-Pair-Programming**: 4-6 Wochen, je nachdem wie viele Stunden täglich

## Offene Punkte / nächster Schritt

Wenn dieser Plan grundsätzlich stimmt, würde ich vorschlagen:

1. Du gehst die fünf "vorab klären"-Fragen oben durch und hältst Antworten im Plan-Dokument fest
2. Wir picken EINEN klaren Track aus Phase 1 (Vorschlag: Auth + Realtime-Token-Endpoint, weil das das technische Rückgrat ist) und prototypen ihn
3. Nach diesem Prototyp wird klar, ob die Stack-Wahl (Hono, Drizzle, etc.) tatsächlich passt oder wir adjustieren
