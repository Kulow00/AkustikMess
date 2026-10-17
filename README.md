# AkustikMess

**Messsoftware für Beschallungstechnik und Raumakustik – für Windows und macOS.**

> Internes Repository (Closed Source). Öffentliche Fehlermeldungen: [Kulow00/AkustikMess-Feedback](https://github.com/Kulow00/AkustikMess-Feedback) · Veröffentlichen: [docs/veroeffentlichen.md](docs/veroeffentlichen.md)

AkustikMess hilft beim Einmessen von Lautsprechersystemen und beim Beurteilen von Räumen. Gemessen wird mit
einem Messmikrofon und einem handelsüblichen Audio-Interface.

**[⬇ Download: akmess.alex-kulow.de](https://akmess.alex-kulow.de)** – die Seite erkennt dein Betriebssystem
und bietet das passende ZIP-Bundle an.

**[📖 Wiki](https://akmess.alex-kulow.de/wiki/index.html)** – Anleitungen zu Messaufbau, allen Modi und häufigen Problemen (Quelle: [docs/wiki](docs/wiki)).

## Funktionen

| Modus | Funktionen |
|---|---|
| **Echtzeit** | Spektrum (Schmalband oder 1/1 … 1/48 Oktave, A/C/Z-Bewertung, Spitzenwert-Halten) · Zweikanal-Übertragungsfunktion (Betrag, Phase, Kohärenz) mit automatischer Laufzeitsuche, Glättung, Kohärenz-Ausblendung · gespeicherte Kurven mit CSV-Export |
| **Impulsantwort** | Sinus-Sweep-Messung mit optionaler Loopback-Referenz und Mittelung · Ansichten: linear, logarithmisch, ETC, Schroeder-Abklingkurve, Spektrogramm, Frequenzgang · EDT, T20, T30, C50, C80, D50, Ts je Oktavband · STI und STIPA · WAV laden/speichern |
| **SPL** | LAF/LAS/LAI, Leq (1 s, 1 min, 15 min, gesamt), Spitzenpegel, Max/Min · Kalibrierung mit Schallkalibrator · Ampel und Alarm · Pegelverlauf · CSV-Protokoll · Ereignisnotizen · HTML-Bericht |
| **Raum** | Raum und Lautsprecher anlegen (Position, Ausrichtung, Pegel, Delay, Polarität, Abstrahlwinkel, Weiche) · Pegelkarte der Hörfläche je Band oder A-bewertet mit phasenrichtiger Summe · Sub-Setups: L/R, Mitte, Broadside, Arc-Delay, Endfire, Cardioid · Bühnenpegel · Messpunkte: Messung vs. Vorhersage · Reflexionen und Nachhall (gemessen oder berechnet) · STI-Karte · animiertes Wellenbild (Draufsicht/Schnitt) · Raummoden · 3D-Ansicht · mehrere Hörflächen (Empore) · Import gemessener Abstrahlung |

**In allen Modi:**
- **Fadenkreuz:** Fährt man mit der Maus über ein Frequenzdiagramm, zeigt es die genaue Frequenz (z. B. 2553 Hz), die Note mit Cent-Abweichung (z. B. D♯7 +44 ct) und den Messwert der Kurve an dieser Stelle.
- **Spektrum-Titel:** Er zeigt die stärkste Spektrallinie genauer als die FFT-Auflösung (±0,02 Hz), ebenfalls mit Note.
- **Kammerton:** Die Schaltfläche **♪ Kammerton** stellt den Bezugston A4 ein: Voreinstellungen (440/442/443/415/432/466 Hz), Eingabe auf 0,01 Hz genau oder **„Ton messen“** – ein gespielter Referenzton wird erkannt und A4 passend gesetzt. Deutsche (H) oder internationale (B) Notennamen.

Ein **Simulationsmodus** (virtueller Raum mit Lautsprecher, ca. 1 s Nachhall und Loopback-Referenz) ermöglicht das Ausprobieren aller Funktionen ohne Audio-Interface.

### Werkzeuge für den Messalltag

| Funktion | So geht's |
|---|---|
| **Zielkurve** | Echtzeit → *Zielkurve*: Flach, Live-Hauskurve, Sprache, X-Kurve oder eigene Datei (Zeilen „Frequenz dB“, auch .frd). Gestrichelte Linie mit Toleranzband; der Pegel wird automatisch an die Messung angeglichen. |
| **Differenz** | Zwei gespeicherte Übertragungsfunktionen markieren (Strg+Klick) → **Differenz A − B**. |
| **Live relativ** | Eine gespeicherte Kurve markieren → **Live relativ zur gewählten Kurve**. Zeigt live die Änderung gegenüber dem Ausgangszustand, ideal beim Einstellen eines EQs. |
| **Crossover-Ausrichtung** | Sub allein und Top allein messen und speichern, beide markieren → **Crossover…**. Laufzeit, Polarität und Pegel von B verschieben, Summe sofort sehen. **Optimum finden** sucht die beste Einstellung im markierten Übergangsbereich. |
| **Sitzungen** | Datei → Speichern/Öffnen (`.akmess`): alle Kurven, Einstellungen, Zielkurve, Impulsantwort, SPL-Verlauf und Notizen. **Automatische Sicherung jede Minute**; nach einem Absturz wird die Wiederherstellung angeboten. |
| **MTW (Multi-Time-Window)** | Standard der Übertragungsfunktion: 8 parallele FFTs von 683 ms (Bass) bis 5,3 ms (Hochton) ergeben etwa 1/24 Oktave Auflösung über den ganzen Bereich. Die Kurve wird ruhiger, Hall zeigt sich ehrlich als niedrigere Kohärenz. Feste FFT-Größen sind weiterhin wählbar. |
| **Generator** | **Rosa Rauschen (periodisch)** passt sich der FFT-Größe an und liefert ohne lange Mittelung ruhige Kurven. Sanftes Ein- und Ausblenden, roter **STUMM**-Knopf, **Pegelgrenze** zum Schutz der Lautsprecher. |

## Installation

Verteilt wird je System ein **ZIP-Bundle** (Programmordner + Startskript + LIESMICH), keine Installation nötig:

**Windows (10/11):** ZIP entpacken, Ordner an einen festen Platz legen, **„AkustikMess starten.bat“** doppelklicken. Das Skript entfernt die Download-Markierung nur für diesen Ordner (sonst blockiert Smart App Control das unsignierte Programm) und startet AkustikMess.

**macOS:** ZIP öffnen, Ordner z. B. nach *Programme* legen, beim ersten Mal **Rechtsklick auf „AkustikMess starten.command“ → Öffnen**. Das Skript entfernt die Quarantäne-Markierung und startet die App. Beim ersten Start den Mikrofonzugriff erlauben.

**Updates:** Beim ersten Start fragt AkustikMess, ob es automatisch nach neuen Versionen suchen darf. Gefundene Updates erscheinen nur als Hinweis in der Statusleiste und unterbrechen nie eine Messung; installiert wird erst nach Bestätigung. Unter *Hilfe → Nach Updates suchen…* lässt sich zwischen dem Kanal **Stabil** und **Beta** (neue Funktionen früher, weniger erprobt) wählen. Updates sind digital signiert und werden vor der Installation geprüft.

## Erste Schritte

1. **Audio-Einstellungen…** → „Simulation (ohne Hardware)“ oder echtes Interface wählen (Windows: ASIO oder WASAPI empfohlen).
2. **▶ Audio starten**, dann **Generator EIN** (rosa Rauschen).
3. *Echtzeit*: **Laufzeit finden**, danach erscheint die Übertragungsfunktion.
4. *Impulsantwort*: **Messen**.
5. *SPL*: zuerst **Kalibrieren…** (94-dB-Kalibrator), sonst werden Werte in dBFS angezeigt.

### Typischer Messaufbau

```
Ausgang 1 ──► Lautsprecher/Mischpult ──► Raum ──► Messmikrofon ──► Eingang 1 (Messung)
    └──────────── Kabel (Loopback) ─────────────────────────────► Eingang 2 (Referenz)
```

### Tastenkürzel (F1 zeigt die Übersicht)

| Taste | Funktion |
|---|---|
| Leertaste | Audio starten/stoppen |
| G / M | Generator ein/aus · sofort stumm |
| S / Umschalt+S | Übertragungsfunktion / Spektrum speichern |
| D · R · P | Laufzeit finden · Mittelung zurücksetzen · Spitzenwert halten |
| Eingabe | Impulsantwort messen |
| N | SPL-Notiz eingeben |
| 1 / 2 / 3 / 4 | Modus wechseln |
| Strg+N/O/S | Sitzung neu/öffnen/speichern |

Einzeltasten wirken nicht, solange in ein Eingabefeld getippt wird.

## Fernbedienung per Handy/Tablet

1. Handy und Rechner ins **selbe WLAN**.
2. Symbolleiste → **📱 Fernbedienung…** → **EIN**, dann den QR-Code mit der Handy-Kamera scannen. Es wird keine App benötigt, nur der Browser.
3. Beim ersten Mal fragt Windows nach der Firewall: **nur „Private Netzwerke“** erlauben.

Auf dem Handy:
- **Übertragung:** Betrag, Kohärenz und Phase live, gespeicherte Kurven als Vergleich. Tippen zeigt Frequenz, Note und Messwert. **Kurve speichern** mit Positionsname (z. B. „Reihe 10 links“), Laufzeit finden, Mittelung zurücksetzen.
- **Spektrum:** live, mit der stärksten Frequenz und Note.
- **SPL:** große Ampel-Anzeige, alle Kennwerte, Notizen setzen.
- **Impuls:** Messung starten, danach STI/STIPA und die Raumakustik-Tabelle.
- **Immer sichtbar:** Generator EIN/AUS, Pegel ±3 dB, STUMM, Eingangspegel.

Die Fernbedienung ist standardmäßig aus und nur mit dem geheimen Schlüssel aus dem QR-Code erreichbar („Neuen Zugangsschlüssel erzeugen“ macht alte QR-Codes ungültig). Sie lädt nichts aus dem Internet und funktioniert deshalb auch in Veranstaltungs-WLANs ohne Internetzugang. Nicht in öffentlichen WLANs verwenden. **Bei aktivem VPN** im Dialog die WLAN-Adresse (meist 192.168.…) wählen oder das VPN trennen.

## Messgenauigkeit und Grenzen

- Die Algorithmen folgen den einschlägigen Normen und sind gegen Sollwerte getestet: Bewertungsfilter (IEC 61672), Bänder (IEC 61260), Nachhallzeit mit Lundeby-Rauschkompensation (ISO 3382), STI (IEC 60268-16).
- Die Genauigkeit „Klasse 1/2“ hängt von **Mikrofon, Interface und Kalibrierung** ab und ist mit dieser Software allein nicht zertifiziert.
- STI/STIPA werden indirekt aus der Impulsantwort berechnet, ohne Hörmaskierung und Hörschwelle.
- Noch nicht umgesetzt: Messung mehrerer Kanalpaare gleichzeitig, Mikrofon-Korrekturdateien.

## Datenschutz

AkustikMess sendet keine Daten über dich oder deine Messungen. Netzwerkzugriffe gibt es nur, wenn du sie erlaubst: die Update-Suche (lädt nur die öffentliche Versionsliste) und die Fernbedienung im lokalen Netzwerk. Messungen und Sitzungen bleiben auf deinem Rechner. Details: [Datenschutzerklärung](https://akmess.alex-kulow.de/datenschutz.html).

## Fehler melden

Nutzer melden Fehler und Ideen im öffentlichen Repository [Kulow00/AkustikMess-Feedback](https://github.com/Kulow00/AkustikMess-Feedback) (Vorlage dafür: [feedback-repo/](feedback-repo)). Im Programm: *Hilfe → Fehler melden / Idee vorschlagen…*

## Entwicklung

### Aus dem Quellcode starten

Benötigt Python 3.12.

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt        # Windows
.venv/bin/pip install -r requirements-dev.txt            # macOS
python -m akustik                                         # Programm starten
python -m pytest tests                                    # Tests ausführen
```

Unter Windows startet auch `start_windows.bat`, unter macOS `start_macos.command` (einmalig `chmod +x start_macos.command`).

| Ordner | Inhalt |
|---|---|
| `akustik/dsp/` | Messalgorithmen (ohne Oberfläche, einzeln testbar) |
| `akustik/audio/` | Audio-Engine (PortAudio) und Simulation |
| `akustik/gui/` | Oberfläche (PySide6 + pyqtgraph) |
| `akustik/remote/` | Fernbedienung (Webserver und Handy-Seite) |
| `tests/` | automatische Tests |

## Lizenz

Copyright © 2026 Alex Kulow. Alle Rechte vorbehalten – Nutzung gemäß den [Nutzungsbedingungen](LICENSE).

Versionen bis einschließlich 0.5.0-beta.5 wurden unter der GNU GPL 3.0 verbreitet und bleiben für deren Empfänger unter dieser Lizenz.

Mitgelieferte Fremdkomponenten (u. a. Qt/PySide6 unter LGPL-3.0) behalten ihre eigenen Lizenzen, siehe [docs/THIRD-PARTY-NOTICES.md](docs/THIRD-PARTY-NOTICES.md).
