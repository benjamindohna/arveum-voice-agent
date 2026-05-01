# 02 — Agent State Machine

Interne Sicht: zwei Top-Level-Modi (`FREE MODE` = Agent A, `APPLY MODE` = Agent B) mit jeweils eigenen Sub-States. Übergänge sind getriggert durch User-Intent oder System-Events.

> **Hinweis zur Renderer-Kompatibilität:** Notion rendert `stateDiagram-v2` (insbesondere mit nested states) unzuverlässig. Diese Datei nutzt deshalb `flowchart`-Syntax mit `subgraph`-Blöcken — semantisch identisch, in Notion / GitHub / mermaid.live zuverlässig darstellbar.

```mermaid
flowchart TD
    Start([Anruf eingeht]) --> Greet["Greeting<br/>KI-Disclosure"]
    Greet --> Consent{Konsens erteilt?}
    Consent -->|Nein| Escalate[Eskalation<br/>an menschlichen Recruiter]
    Consent -->|Ja| Chat

    subgraph Free["FREE MODE — Agent A"]
        direction TB
        Chat[Chat aktiv] -->|strukturierte Frage<br/>z.B. Urlaubstage| ToolInv[Tool-Aufruf]
        ToolInv --> Chat
        Chat -->|Bewerbungssignal erkannt| Intent[User moechte sich bewerben]
        Intent -->|User lehnt ab| Chat
        Intent -->|User akzeptiert| ListJobs[Stellen-Listing]
        ListJobs --> RoleSel[Rolle auswaehlen]
        RoleSel -->|mehr Infos| RoleDet[Role Details]
        RoleDet --> RoleSel
        RoleSel -->|andere Rollen anzeigen| ListJobs
        RoleSel -->|Rolle gewaehlt| RoleConf[Rolle bestaetigt]
        RoleConf --> Commit[Commitment Check<br/>15 Min, fokussiert]
        Commit -->|spaeter| Chat
    end

    Commit -->|Commit erteilt| Email
    Chat -.User legt auf.-> Abandon[(State persistiert<br/>30 Tage)]
    Chat -.Mensch gewuenscht.-> Escalate

    subgraph Apply["APPLY MODE — Agent B"]
        direction TB
        Email[Email Capture] --> LinkSent[Magic Link versandt]
        LinkSent --> WaitUp[Warten auf Upload]
        WaitUp -->|Upload empfangen| Parsed[CV geparst]
        WaitUp -->|Timeout 5 Min| ResendLink[Link erneut senden]
        ResendLink --> WaitUp
        Parsed --> QGen[Question-Gen<br/>laeuft im Hintergrund]
        QGen -->|erste Frage bereit| Interview[Interview Q und A]
        Interview -->|naechste Frage| Interview
        Interview -->|Q-Pool erschoepft<br/>oder adaptives Ende| Wrap[Wrapping]
        Wrap --> Done[Bestaetigungs-Email versandt]
    end

    Email -.Mensch gewuenscht.-> Escalate
    Interview -.Mensch gewuenscht.-> Escalate
    WaitUp -.User legt auf.-> Abandon
    Interview -.User legt auf.-> Abandon

    Done --> CallEnd([Call beendet])
    Escalate --> CallEnd
    Abandon -.Wiederanruf.-> Greet
    Abandon -.Timeout 30 Tage.-> CallEnd

    classDef offRamp fill:#fff3cd,stroke:#856404,color:#000
    classDef terminal fill:#d4edda,stroke:#155724,color:#000
    classDef apply fill:#cce5ff,stroke:#004085,color:#000

    class Escalate,Abandon,ResendLink offRamp
    class CallEnd terminal
    class Email,LinkSent,WaitUp,Parsed,QGen,Interview,Wrap,Done apply
```

## Wichtige State-Invarianten

| Invariante | Bedeutung |
|---|---|
| **Konsens vor allen Sub-States** | Kein Übergang aus `Greeting` ohne explizit dokumentierten Konsens |
| **Eskalation aus jedem State erreichbar** | Trigger-Wörter ("Mensch", "echter Recruiter") = sofortiger Übergang |
| **State-Persistierung** | Bei Abbruch wird letzter Sub-State + Kontext gespeichert (Schlüssel: Telefon + Email) |
| **DSGVO-Löschfrist** | Persisted State automatisch nach 30 Tagen gelöscht (oder konfigurabel pro Mandant) |
| **Modus-Wechsel nur in eine Richtung** | `FREE MODE → APPLY MODE` per Commitment. Rückkehr nur über erneuten Trigger oder Eskalation |

## Prompt-Design pro Modus

### FREE MODE System-Prompt (Skizze)
- Persona: warm, kompetent, neugierig — wie ein erfahrener Mitarbeiter, der gern erzählt
- Wissensbasis: in-context Briefing + Tool-Liste mit klaren Anwendungsregeln
- **Anti-Halluzinations-Regel**: konkrete Zahlen / Stellen / Benefits *immer* via Tool, nie schätzen
- Bridge-Trigger: erkenne Bewerbungssignale, frage explizit nach
- Off-Ramp: bei Trigger-Wörtern sofort eskalieren

### APPLY MODE System-Prompt (Skizze)
- Persona: fokussiert, strukturiert, freundlich aber zielgerichtet
- Strikte State-Maschine: kein "Plaudern", außer kurze Bridge zur Latenz-Überbrückung
- Question-Bank: dynamisch generiert pro CV + Rolle, mit Schwierigkeitsgrad
- Adaptive Beendigung: nach 8–12 Fragen oder bei klarer Score-Konvergenz
- **Pass-Mechanik**: User darf eine Frage überspringen ohne Begründung

## Was gehört bewusst NICHT in einen Sub-Agent

- Stellen-Listing → **Tool**, nicht Agent
- CV-Parsing → **Async-Service**, nicht Agent
- Scoring → **Post-Call Pipeline**, nicht im Live-Agent

Sub-Agenten lohnen sich nur, wenn sie eigene Persona + eigenes Tool-Set + eigenen Prompt brauchen. Hier ist ein Tool / Service ausreichend und latenz-freundlicher.
