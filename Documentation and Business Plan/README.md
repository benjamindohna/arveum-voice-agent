# Arveum Call Agent — Flow-Dokumentation

Drei Diagramme beschreiben zusammen den vollständigen Flow eines Bewerbungs-Calls, jeweils auf einem anderen Abstraktionslayer:

| Datei | Layer | Zielgruppe |
|---|---|---|
| `01-user-journey.md` | Was der Anrufer erlebt | Produkt, UX, Stakeholder |
| `02-agent-state-machine.md` | Interne Modi & Übergänge | Engineering, Prompt-Design |
| `03-backend-architecture.md` | Services, Tools & Datenflüsse | Engineering, Compliance |

## Wie ansehen

Die Dateien enthalten **Mermaid**-Diagramme. Render funktioniert in:
- GitHub / GitLab (nativ in Markdown)
- Notion (Mermaid-Block einfügen)
- VS Code (Extension: "Markdown Preview Mermaid Support")
- Online ad-hoc: https://mermaid.live (Block reinkopieren)

## Konventionen

- **Gelb** = Off-Ramp (Mensch-Eskalation, Pause, Abbruch)
- **Blau** = Apply Mode (deterministischer Bewerbungs-Pfad)
- **Grün** = Terminal-State
- **Gestrichelt** = asynchroner Pfad oder Wiederaufnahme

## Kern-Designentscheidungen (Stand 2026-04-30)

1. **Zwei Modi** statt einem: `Free Mode` (offene Konversation) und `Apply Mode` (deterministisch). Expliziter Übergang mit Commitment-Check.
2. **Hybrid-Wissen**: kompaktes Firmen-Briefing in-context (~3–8k Tokens) + **Tools** für strukturierte Fakten (Stellen, Benefits, Standorte). Kein RAG für die meisten Use Cases — Latenz-Killer bei Voice.
3. **Off-Ramp an jedem Knoten**: User muss jederzeit zu menschlichem Recruiter kommen können (Compliance + Trust + EU AI Act Art. 14).
4. **State-Persistierung** über Telefonnummer und/oder Email als Schlüssel — Wiederanruf-fähig.
5. **Bridge-Mechanik** während Wartezeiten (CV-Upload, Question-Generation): keine peinliche Stille.

## Offene Design-Entscheidungen

- Voice-Provider: LiveKit / Vapi / Retell / Twilio — noch nicht festgelegt
- STT/TTS-Stack (Latenz vs. Qualität, deutscher Sprachraum)
- CV-Parser: eigen vs. Affinda / Sovren / RChilli
- ATS-Integrationsreihenfolge (Personio first?)
- Scoring-Modell und Bias-Audit-Pipeline (EU AI Act Art. 10)

## Compliance-Touchpoints (in allen Diagrammen markiert)

- 🤖 **KI-Disclosure** (EU AI Act Art. 50, DSGVO Transparenz)
- 🎙️ **Aufzeichnungs-Konsens** (TKG, BDSG)
- 📋 **Zweckbindung** der Datenverarbeitung
- 🚪 **Mensch-Eskalation** verfügbar
- 🗑️ **Recht auf Löschung** in jeder Bestätigungs-Email
