# Änderungsprotokoll

Alle nennenswerten Änderungen an AkustikMess. Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionsnummern nach [Semantic Versioning](https://semver.org/lang/de/):

- `MAJOR.MINOR.PATCH`: stabile Version (z. B. `1.2.3`)
- `MAJOR.MINOR.PATCH-beta.N`: Vorabversion für den Beta-Kanal (z. B. `1.3.0-beta.2`)

Neue Einträge zuerst unter **[Unreleased]** sammeln. `tools/release.py` macht daraus beim
Veröffentlichen den Abschnitt der neuen Version und übernimmt ihn als Patch Notes.

## [Unreleased]

### Neu
- Neuer Modus **Raum** (Taste 4): Lautsprecher im Raum planen, Pegelkarte der Hörfläche je Frequenzband oder A-bewertet, Sub-Setups (L/R, Mitte, Broadside, Arc, Endfire, Cardioid) mit automatischen Delays, Bühnenpegel, Messpunkte mit Vergleich Messung ↔ Vorhersage
- Wiki-Seite „Raum“

## [0.5.0-beta.5] - 2026-10-16

### Neu
- Darstellungsbereich in der Seitenleiste einstellbar: Frequenz von/bis, Pegelbereich für Spektrum und Betrag; folgt auch dem Zoomen mit der Maus

### Verbessert
- Fadenkreuz zeigt die Messwerte live an, auch wenn die Maus im Diagramm stillsteht
- Generator einschalten startet das Audio automatisch; Hinweis, wenn kein Ausgangsgerät gewählt ist
- Audio-Einstellungen schlagen immer ein Ausgangsgerät vor (gleiches Gerät oder System-Standard)

### Behoben
- Generator spielte teilweise nicht ab, wenn Ein- und Ausgang verschiedene Geräte sind (z. B. macOS: eingebautes Mikrofon + Lautsprecher)
- Übertragungsfunktion und Phase hatten regelmäßig Lücken: das Ausblenden bei geringer Kohärenz bewertet jetzt Bereiche statt Einzelpunkte
- Zoom im Spektrum ist auf −150 dB begrenzt

## [0.5.0-beta.4] - 2026-10-16

### Neu
- Lizenzen: kostenlose Registrierung mit persönlichem Lizenzschlüssel (Hilfe → Lizenz…); die Prüfung läuft nur auf dem eigenen Rechner
- Neue Homepage mit Wiki (Erste Schritte, Messaufbau, alle Modi, Fernbedienung, Lizenz, häufige Probleme), Datenschutz und Impressum
- Über AkustikMess zeigt die Lizenz

## [0.5.0-beta.3] - 2026-10-16

### Neu
- AkustikMess ist Open Source (GNU GPL 3.0 oder neuer)
- Hilfe → Über AkustikMess zeigt Urheber, Lizenz und Gewährleistungsausschluss
- Programm und Windows-Installer werden signiert (SignPath Foundation): Windows Smart App Control blockiert die Installation nicht mehr
- Download-Seite mit Links zu Quellcode, Lizenz, Datenschutz und Code-Signatur

### Geändert
- Automatische Update-Suche erst nach Zustimmung beim ersten Start (ohne Zustimmung keine Netzwerkverbindung)
- Programmdatei mit Produktname und Versionsnummer in den Datei-Eigenschaften

## [0.5.0-beta.2] - 2026-10-16

Erste öffentlich verteilte Beta (0.5.0-beta.1 war ein interner Test-Build).

### Neu
- Download-Seite **akmess.alex-kulow.de** mit automatischer Betriebssystem-Erkennung und Patch Notes
- Installer für Windows (ohne Administratorrechte) und macOS
- Automatische Updates mit Kanälen **Stabil** und **Beta**; signierte Releases, geprüfte Downloads
- Updates unterbrechen keine Messung: Hinweis in der Statusleiste, Installation nur nach Bestätigung
- Menü Hilfe → „Nach Updates suchen…“ und „Über AkustikMess“

## [0.4.0] - 2026-10-16

### Neu
- Fernbedienung per Handy/Tablet über den Browser (QR-Code, keine App nötig)
- Auf dem Handy: Übertragungsfunktion, Spektrum, SPL, Impulsantwort-Messung, Generator und Notizen

### Behoben
- Gespeicherte Kurven hatten dieselbe Farbe wie die Live-Kurve

## [0.3.0] - 2026-10-16

### Neu
- Multi-Time-Window-FFT (MTW) als Standard der Übertragungsfunktion

### Geändert
- Standard-Kohärenzschwelle 0,3

## [0.2.0] - 2026-10-16

### Neu
- Zielkurven mit Toleranzband, Differenz A − B, Live relativ zu gespeicherter Kurve
- Crossover-Ausrichtung (virtuelle Summe, Optimum finden)
- Tastenkürzel, Sitzungen speichern/laden, automatische Sicherung
- Periodisches rosa Rauschen, Ein-/Ausblenden, STUMM, Pegelgrenze

## [0.1.0] - 2026-10-15

### Neu
- Erste Version: Echtzeit-Spektrum und Übertragungsfunktion, Impulsantwort mit Raumakustik und STI, SPL-Messung
- Präzise Frequenz- und Notenanzeige, Kammerton-Kalibrierung
