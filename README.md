# AkustikMess

Messsoftware für Beschallungstechnik und Raumakustik (Windows und macOS) mit drei Modi:

| Modus | Funktionen |
|---|---|
| **Echtzeit** | Spektrum (Schmalband oder 1/1 … 1/48 Oktave, A/C/Z-Bewertung, Spitzenwert-Halten) · Zweikanal-Übertragungsfunktion (Betrag, Phase, Kohärenz) mit automatischer Laufzeitsuche, Glättung, Kohärenz-Ausblendung · gespeicherte Kurven mit CSV-Export |
| **Impulsantwort** | Sinus-Sweep-Messung mit optionaler Loopback-Referenz und Mittelung · Ansichten: linear, logarithmisch, ETC, Schroeder-Abklingkurve, Spektrogramm, Frequenzgang · EDT, T20, T30, C50, C80, D50, Ts je Oktavband · STI und STIPA · WAV laden/speichern |
| **SPL** | LAF/LAS/LAI, Leq (1 s, 1 min, 15 min, gesamt), Spitzenpegel, Max/Min · Kalibrierung mit Schallkalibrator · Ampel und Alarm · Pegelverlauf · CSV-Protokoll · Ereignisnotizen · HTML-Bericht |

**In allen Modi:**
- **Fadenkreuz:** Fährt man mit der Maus über ein Frequenzdiagramm, zeigt es die genaue Frequenz (z. B. 2553 Hz), die Note mit Cent-Abweichung (z. B. D♯7 +44 ct) und den Messwert der Kurve an dieser Stelle.
- **Spektrum-Titel:** Er zeigt die stärkste Spektrallinie genauer als die FFT-Auflösung (±0,02 Hz), ebenfalls mit Note.
- **Kammerton:** Die Schaltfläche **♪ Kammerton** in der Symbolleiste stellt den Bezugston A4 ein. Es gibt Voreinstellungen (440/442/443/415/432/466 Hz), eine Eingabe auf 0,01 Hz genau und **„Ton messen“**: Ein gespielter Referenzton wird erkannt, und A4 wird so gesetzt, dass dieser Ton exakt stimmt. Wählbar sind deutsche (H) oder internationale (B) Notennamen.

Ein **Simulationsmodus** (virtueller Raum mit Lautsprecher, ca. 1 s Nachhall und Loopback-Referenz) ermöglicht das Ausprobieren aller Funktionen ohne Audio-Interface.

**Download:** https://akmess.alex-kulow.de · **Lizenz:** [GPL-3.0](LICENSE) · [Fremdkomponenten](docs/THIRD-PARTY-NOTICES.md) · [Code-Signatur und Datenschutz](docs/code-signing-policy.md)

> Free code signing provided by [SignPath.io](https://about.signpath.io/), certificate by [SignPath Foundation](https://signpath.org/).

## Workflow-Funktionen

| Funktion | So geht's |
|---|---|
| **Zielkurve** | Echtzeit → *Zielkurve*: Flach, Live-Hauskurve, Sprache, X-Kurve oder eigene Datei (Zeilen „Frequenz dB“, auch .frd). Gestrichelte Linie mit Toleranzband; der Pegel wird automatisch an die Messung angeglichen. |
| **Differenz** | Zwei gespeicherte Übertragungsfunktionen markieren (Strg+Klick) → **Differenz A − B**. |
| **Live relativ** | Eine gespeicherte Kurve markieren → **Live relativ zur gewählten Kurve**. Zeigt live die Änderung gegenüber dem Ausgangszustand, ideal beim Einstellen eines EQs. |
| **Crossover-Ausrichtung** | Sub allein und Top allein messen und speichern, beide markieren → **Crossover…**. Laufzeit, Polarität und Pegel von B verschieben, Summe sofort sehen. **Optimum finden** sucht die beste Einstellung im markierten Übergangsbereich, den man mit der Maus verschieben kann. |
| **Sitzungen** | Datei → Speichern/Öffnen (`.akmess`): alle Kurven, Einstellungen, Zielkurve, Impulsantwort, SPL-Verlauf und Notizen. **Automatische Sicherung jede Minute**; nach einem Absturz wird die Wiederherstellung angeboten. |
| **MTW (Multi-Time-Window)** | Standard der Übertragungsfunktion. 8 parallele FFTs von 683 ms (Bass) bis 5,3 ms (Hochton) ergeben etwa 1/24 Oktave Auflösung über den ganzen Bereich. Späte Reflexionen fallen im Hochton aus dem Fenster: Die Kurve wird ruhiger, Hall zeigt sich ehrlich als niedrigere Kohärenz. Feste FFT-Größen sind weiterhin wählbar. |
| **Generator** | **Rosa Rauschen (periodisch)** passt sich der FFT-Größe an und liefert ohne lange Mittelung ruhige Kurven. Sanftes Ein- und Ausblenden, roter **STUMM**-Knopf, **Pegelgrenze** zum Schutz der Lautsprecher (Menü Generator). |

## Fernbedienung per Handy/Tablet

1. Handy und Laptop ins **selbe WLAN**.
2. Symbolleiste → **📱 Fernbedienung…** → **EIN**, dann den QR-Code mit der Handy-Kamera scannen. Es wird keine App benötigt, nur der Browser.
3. Beim ersten Mal fragt Windows nach der Firewall: **nur „Private Netzwerke“** erlauben.

Auf dem Handy:
- **Übertragung:** Betrag, Kohärenz und Phase live, gespeicherte Kurven als Vergleich. Tippen zeigt die genaue Frequenz, die Note und den Messwert. **Kurve speichern** mit Positionsname (z. B. „Reihe 10 links“), dazu Laufzeit finden und Mittelung zurücksetzen.
- **Spektrum:** live, mit der stärksten Frequenz und Note.
- **SPL:** große Ampel-Anzeige, alle Kennwerte, Notizen setzen.
- **Impuls:** Messung starten, danach STI/STIPA und die Raumakustik-Tabelle.
- **Immer sichtbar:** Generator EIN/AUS, Pegel ±3 dB, STUMM, Eingangspegel.

**Sicherheit:**
- Die Fernbedienung ist standardmäßig aus.
- Ohne den geheimen Schlüssel im QR-Code antwortet der Server nicht.
- „Neuen Zugangsschlüssel erzeugen“ macht alte QR-Codes ungültig.
- Nicht in öffentlichen WLANs verwenden.

Die Seite lädt nichts aus dem Internet und funktioniert deshalb auch in Veranstaltungs-WLANs ohne Internetzugang. **Bei aktivem VPN** am Laptop kann das Handy den Laptop eventuell nicht erreichen. Im Dialog dann die WLAN-Adresse (meist 192.168.…) wählen oder das VPN trennen.

### Tastenkürzel (F1 zeigt die Übersicht)

| Taste | Funktion |
|---|---|
| Leertaste | Audio starten/stoppen |
| G / M | Generator ein/aus · sofort stumm |
| S / Umschalt+S | Übertragungsfunktion / Spektrum speichern |
| D · R · P | Laufzeit finden · Mittelung zurücksetzen · Spitzenwert halten |
| Eingabe | Impulsantwort messen |
| N | SPL-Notiz eingeben |
| 1 / 2 / 3 | Modus wechseln |
| Strg+N/O/S | Sitzung neu/öffnen/speichern |

Einzeltasten wirken nicht, solange in ein Eingabefeld getippt wird.

## Starten

**Windows:** `start_windows.bat` doppelklicken, oder die fertige Version in `dist\AkustikMess\AkustikMess.exe` starten.

**macOS:** Einmalig im Terminal `chmod +x start_macos.command` ausführen, danach doppelklicken. Benötigt Python 3.11+ von python.org. Beim ersten Start fragt macOS nach dem Mikrofonzugriff, der erlaubt werden muss.

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

## Teilen, Installer und Updates

**Für Empfänger:** ein Link auf die Download-Seite (`index.html` im Veröffentlichungsordner). Sie erkennt Windows bzw. macOS, bietet die passende Datei an, zeigt alle anderen Systeme, hat einen Umschalter Stabil/Beta und zeigt die Patch Notes. Jeder Installer ist **eine einzelne Datei mit allem Nötigen**, auf dem Zielrechner wird nichts nachgeladen. Unter Windows sind keine Administratorrechte nötig.

**Updates im Programm:**
- Menü Hilfe → *Nach Updates suchen…*: Kanal **Stabil** oder **Beta**, Patch Notes aller neuen Versionen, *Herunterladen und installieren*.
- Beim ersten Start fragt das Programm, ob es automatisch nach Updates suchen darf (ohne Zustimmung keine Netzwerkverbindung). Dann wird bei jedem Start im Hintergrund geprüft. Ein gefundenes Update erscheint nur als Hinweis in der Statusleiste und unterbricht nie eine Messung.
- Unter Windows läuft die Installation still. Das Programm schließt sich, aktualisiert sich und startet neu; die Sitzung wird vorher gesichert.
- Unter macOS öffnet sich das macOS-Installationsprogramm.

**Sicherheit:**
- Das Release-Verzeichnis ist mit einem Ed25519-Schlüssel signiert, jede Datei wird per SHA-256 geprüft. Manipulierte Updates lehnt das Programm ab, auch wenn Server oder Dropbox kompromittiert sind.
- Erlaubt sind nur https-Adressen (Ausnahme: localhost zum Testen).

### Versionen und Kanäle
- Stabil: `1.2.3` · Beta: `1.3.0-beta.1`, `1.3.0-beta.2`, … → dann `1.3.0` stabil.
- Beta-Nutzer bekommen immer die neueste Version, auch eine neuere stabile.
- Patch Notes in `CHANGELOG.md` unter **[Unreleased]** sammeln. Beim Veröffentlichen werden sie automatisch zur neuen Version.

### Veröffentlichen (Rechner mit Signaturschlüssel)
```bash
python tools/release.py keygen                                   # einmalig – Schlüsseldatei sichern!
python tools/release.py configure --mode selfhosted --publish-dir <Webordner> --base-url https://<server>/akustikmess/
python tools/release.py configure-github --repo NAME/akustikmess # einmalig: über GitHub bauen und signieren
python tools/release.py release --channel beta                   # z. B. 0.5.0-beta.3 → Tag auf GitHub
python tools/release.py publish --wait                           # signierten Installer holen und hochladen
python tools/release.py status                                   # Übersicht
```
**Mit GitHub (Standard, sobald `configure-github` gesetzt ist):** `release` erhöht die Version, übernimmt die Patch Notes, testet, committet und pusht das Tag `v<version>`. GitHub Actions (`.github/workflows/release.yml`) baut Windows und macOS, lässt Programm und Installer von SignPath signieren und legt das GitHub-Release an. `publish --wait` holt den Installer, prüft Prüfsumme und Windows-Signatur, signiert `releases.json` und lädt hoch. Einrichtung: [docs/signpath-einrichtung.md](docs/signpath-einrichtung.md).

**Lokal (`release --local`, ohne GitHub):** Version erhöhen → Patch Notes übernehmen → Tests → Programm bauen → Installer bauen → veröffentlichen, unsigniert. Schlägt ein Schritt fehl, werden Version und `CHANGELOG.md` zurückgesetzt.

**Upload auf akmess.alex-kulow.de (SFTP):** Nach jedem `release`/`add-asset` lädt das Werkzeug automatisch hoch: zuerst die Installer, zuletzt `releases.json`, und prüft danach online Signatur und Erreichbarkeit. Bricht die Verbindung ab, wird neu verbunden und ab der Abbruchstelle fortgesetzt; manuell geht das mit `python tools/release.py upload`. Weitere Befehle: `check-online` und `status`. Die Server-Einrichtung steht in `docs/server-einrichtung.md`. Schlüssel liegen unter `~/.akustikmess/` (Signatur- und Upload-Schlüssel), **beide sichern**.

**Eigener Server:** Jeder Webspace, jedes NAS mit Webserver oder ein statisches Hosting (z. B. GitHub Pages, Netlify, Cloudflare Pages) funktioniert, solange es per https erreichbar ist. Der Veröffentlichungsordner wird 1:1 hochgeladen.

**Dropbox:**
1. `configure --mode dropbox --publish-dir "<Dropbox-Ordner>"` ausführen.
2. Dropbox zeigt keine Webseiten an. Geteilt werden deshalb die Freigabelinks der Dateien, nicht `index.html`.
3. Nach dem ersten Release in Dropbox je einen Freigabelink für `releases.json` und die Installer (`stable/…`, `beta/…`) erstellen.
4. Die Links in `release_config.json` → `dropbox_links` eintragen, dann `configure` erneut und `relink` ausführen.
5. Die Dateinamen bleiben je Kanal gleich, damit die Links beim Überschreiben gültig bleiben. Versionierte Kopien liegen in `archiv/`.

**macOS-Installer:** Baut GitHub Actions bei jedem Release mit (`publish --platform windows --platform macos` übernimmt ihn). Alternativ auf einem Mac: `tools/build_macos.sh`, dann `release.py add-asset --platform macos --file …`.

**Hinweis Code-Signatur:**
- **Windows:** Programm und Installer werden kostenlos über die SignPath Foundation signiert. Ohne Signatur blockiert Windows **Smart App Control** heruntergeladene Installer komplett; `publish` lehnt unsignierte Windows-Installer deshalb ab. SmartScreen kann bei neuen Versionen anfangs noch „Unbekannte App“ melden.
- **macOS:** Ohne Apple-Developer-Konto (99 $/Jahr) und Notarisierung blockiert Gatekeeper den ersten Start (Rechtsklick → Öffnen).
- Die Update-Signatur von AkustikMess (`releases.json`) ist davon unabhängig.

## Messgenauigkeit und Grenzen

- Die Normalgorithmen sind gegen Sollwerte getestet (`tests/`): Bewertungsfilter (IEC 61672), Bänder (IEC 61260), Nachhallzeit mit Lundeby-Rauschkompensation (ISO 3382), STI-Theorie (IEC 60268-16).
- Die Genauigkeit „Klasse 1/2“ hängt von **Mikrofon, Interface und Kalibrierung** ab und ist mit dieser Software allein nicht zertifiziert.
- STI/STIPA werden indirekt aus der Impulsantwort berechnet, ohne Hörmaskierung und Hörschwelle (dafür wären kalibrierte Bandpegel nötig).
- Noch nicht umgesetzt: Messung mehrerer Kanalpaare gleichzeitig, Mikrofon-Korrekturdateien.

## Entwicklung

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt        # Windows
.venv/bin/pip install -r requirements-dev.txt            # macOS
python -m pytest tests                                    # 100 Tests
python -m akustik                                         # Programm starten
pip install pyinstaller && pyinstaller akustikmess.spec   # eigenständiges Programm bauen
```

Die macOS-`.app` muss auf einem Mac gebaut werden (PyInstaller baut nur für das eigene System).

| Ordner | Inhalt |
|---|---|
| `akustik/dsp/` | Messalgorithmen (ohne GUI, testbar) |
| `akustik/audio/` | Audio-Engine (PortAudio) und Simulation |
| `akustik/gui/` | Oberfläche (PySide6 + pyqtgraph) |
| `tests/` | automatische Tests |
| `tools/` | Release-Werkzeug (Build, Signatur des Release-Verzeichnisses, SFTP-Upload) |
| `installer/` | Windows-Installer (Inno Setup) und Download-Seite |
| `.github/workflows/` | Tests bei jedem Push, Release-Build mit SignPath-Signatur |

## Lizenz

Copyright © 2026 Alex Kulow.

AkustikMess ist freie Software: Du kannst sie unter den Bedingungen der [GNU General Public License](LICENSE), Version 3 oder (nach deiner Wahl) jeder späteren Version, weitergeben und/oder verändern. Sie wird OHNE JEDE GEWÄHRLEISTUNG bereitgestellt. Wer eine veränderte Fassung weitergibt, muss deren Quellcode ebenfalls unter der GPL veröffentlichen.

Das Urheberrecht bleibt bei Alex Kulow. Beiträge anderer werden nur unter den Bedingungen in [CONTRIBUTING.md](CONTRIBUTING.md) übernommen.

Mitgelieferte Fremdkomponenten (u. a. Qt/PySide6 unter LGPL-3.0) behalten ihre eigenen Lizenzen, siehe [docs/THIRD-PARTY-NOTICES.md](docs/THIRD-PARTY-NOTICES.md).
