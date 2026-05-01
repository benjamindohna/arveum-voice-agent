# 01 — User Journey

Linearer End-to-End-Flow aus Sicht des Anrufers. Zeigt alle Hauptpfade und Off-Ramps.

```mermaid
flowchart TD
    Start([Anrufer wählt Nummer]) --> Greet["Begrüßung<br/>🤖 KI-Disclosure"]
    Greet --> Consent{"🎙️ Konsens für<br/>Aufzeichnung & KI?"}
    Consent -->|Nein| HumanRoute["🚪 Weiterleitung an<br/>menschlichen Recruiter"]
    Consent -->|Ja| Free["<b>FREE MODE</b><br/>Offene Fragen über Firma,<br/>Kultur, Benefits, Jobs"]

    Free -->|Strukturierte Fakten<br/>z.B. Urlaubstage| ToolCall["Tool-Aufruf<br/>get_benefit / get_office / ..."]
    ToolCall --> Free

    Free -->|Bewerbungsinteresse<br/>erkannt| Bridge["Soft-Bridge:<br/>Sollen wir die offenen<br/>Stellen anschauen?"]
    Free -->|Mensch gewünscht| HumanRoute
    Free -->|User legt auf| Abandon[("State persistiert<br/>für Wiederanruf")]

    Bridge -->|Nein, weiter chatten| Free
    Bridge -->|Ja| ListJobs["Stellen-Liste vorlesen<br/>list_open_jobs()"]

    ListJobs --> Pick{Rolle ausgewählt?}
    Pick -->|Mehr Infos zu Rolle X| Detail["Rollendetails<br/>get_job_details(id)"]
    Detail --> Pick
    Pick -->|Keine passt| Free
    Pick -->|Rolle X gewählt| Confirm["Bestätigung:<br/>Auf Rolle X bewerben?"]

    Confirm -->|Nein| ListJobs
    Confirm -->|Ja| Commit["Hinweis:<br/>~15 Min, volle Aufmerksamkeit,<br/>keine Nebenfragen"]

    Commit -->|Lieber später| Pause[("Rückruf-Termin<br/>vereinbaren")]
    Pause --> StillAsk{Noch weitere<br/>Fragen offen?}
    StillAsk -->|Ja, kurz noch| Free
    StillAsk -->|Nein, alles klar| End
    Commit -->|Los geht's| ApplyEntry[/"--- APPLY MODE ---"/]

    ApplyEntry --> Email["Email-Adresse erfragen<br/>+ Magic-Link-Verifikation"]
    Email --> SendLink["Link versenden<br/>+ Smalltalk-Bridge"]
    SendLink --> Upload{CV hochgeladen?}
    Upload -->|Timeout 5 Min| Retry["Link erneut senden<br/>oder telefonische Alternative"]
    Retry --> Upload
    Upload -->|Ja| BridgeQ["Bridge-Frage stellen<br/>Question-Gen läuft parallel"]

    BridgeQ --> Interview["Adaptive Q&A<br/>8–12 Fragen,<br/>Pass-Mechanik erlaubt"]
    Interview -->|Mensch gewünscht| HumanRoute

    Interview --> Wrap["Abschluss:<br/>Zusammenfassung +<br/>nächste Schritte"]
    Wrap --> ConfirmMail["Bestätigungs-Email an Bewerber<br/>🗑️ inkl. DSGVO-Löschlink<br/>(löscht Bewerberdaten auf Klick)"]
    ConfirmMail --> End([Call beendet])

    HumanRoute --> End
    Abandon -.Wiederanruf.-> Greet
    Pause -.Geplanter Rückruf<br/>(neuer Anruf später).-> Greet

    classDef offRamp fill:#fff3cd,stroke:#856404,color:#000
    classDef terminal fill:#d4edda,stroke:#155724,color:#000
    classDef apply fill:#cce5ff,stroke:#004085,color:#000
    classDef compliance fill:#f8d7da,stroke:#721c24,color:#000

    class HumanRoute,Abandon,Pause,Retry offRamp
    class End terminal
    class Email,SendLink,Upload,BridgeQ,Interview,Wrap,ConfirmMail apply
    class Greet,Consent,ConfirmMail compliance
```

## Kritische Übergänge

| # | Übergang | Warum heikel |
|---|---|---|
| 1 | Free → Bridge | Intent-Detection; zu früh = aufdringlich, zu spät = verpasste Conversion |
| 2 | Confirm → Commit | letzte Chance zum Rückzug; Commitment-Vertrag mit User |
| 3 | SendLink → Upload | Wartezeit von 30s–5min ohne Mensch dahinter; Bridge-Smalltalk Pflicht |
| 4 | Upload → BridgeQ | Question-Gen dauert 5–15s; ohne Bridge-Frage = peinliche Stille |
| 5 | Interview → Wrap | Adaptive Beendigung — wann genug? |

## Off-Ramp-Strategie

Jeder blaue Apply-Mode-Knoten muss eine **explizite "Mensch sprechen"-Option** unterstützen. Im Prompt verankert: *„Wenn der Nutzer das Wort 'Mensch', 'echter Recruiter', 'jemand anderes' sagt, sofort eskalieren ohne Rückfrage."*

## Was nicht im Diagramm steht

- **Identifikation per Telefonnummer** vor Greeting: Wiederanrufer? Existierender Bewerbungsstatus? Spart Doppelarbeit.
- **Sprachwahl** (DE/EN/...): am Anfang erkennen oder explizit fragen.
- **Audio-Qualität-Check**: bei sehr schlechter Verbindung früh anbieten zurückzurufen.
