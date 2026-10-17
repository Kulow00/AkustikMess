# Veröffentlichen (nur für den Projektinhaber)

Interne Anleitung für Releases von AkustikMess. Für Nutzer nicht relevant.
Server: [server-einrichtung.md](server-einrichtung.md) ·
Lizenzen und Homepage: [lizenzsystem.md](lizenzsystem.md), [lizenzserver-einrichtung.md](lizenzserver-einrichtung.md)

Homepage (Startseite, Wiki aus `docs/wiki/`, Lizenz, Datenschutz, Impressum) wird bei jedem Release mitgebaut;
nur die Homepage aktualisieren: `python tools/release.py site`.

## Versionen und Kanäle
- Stabil: `1.2.3` · Beta: `1.3.0-beta.1`, `1.3.0-beta.2`, … → dann `1.3.0` stabil.
- Beta-Nutzer bekommen immer die neueste Version, auch eine neuere stabile.
- Patch Notes in `CHANGELOG.md` unter **[Unreleased]** sammeln. Beim Veröffentlichen werden sie automatisch zur neuen Version.

## Veröffentlichen (Rechner mit Signaturschlüssel)
```bash
python tools/release.py keygen                                   # einmalig – Schlüsseldatei sichern!
python tools/release.py configure --mode selfhosted --publish-dir <Webordner> --base-url https://<server>/akustikmess/
python tools/release.py configure-github --repo NAME/akustikmess # einmalig: über GitHub bauen und signieren
python tools/release.py release --channel beta                   # z. B. 0.5.0-beta.3 → Tag auf GitHub
python tools/release.py publish --wait                           # signierten Installer holen und hochladen
python tools/release.py status                                   # Übersicht
```
**Mit GitHub (Standard, sobald `configure-github` gesetzt ist):** `release` erhöht die Version, übernimmt die Patch Notes, testet, committet und pusht das Tag `v<version>`. GitHub Actions (`.github/workflows/release.yml`) baut Windows und macOS, lässt Programm und Installer von SignPath signieren und legt das GitHub-Release an. `publish --wait` holt den Installer, prüft Prüfsumme und Windows-Signatur, signiert `releases.json` und lädt hoch. Einrichtung: [docs/signpath-einrichtung.md](signpath-einrichtung.md).

**Lokal (`release --local`, ohne GitHub):** Version erhöhen → Patch Notes übernehmen → Tests → Programm bauen → Installer bauen → veröffentlichen, unsigniert. Schlägt ein Schritt fehl, werden Version und `CHANGELOG.md` zurückgesetzt.

**Upload auf akmess.alex-kulow.de (SFTP):** Nach jedem `release`/`add-asset` lädt das Werkzeug automatisch hoch: zuerst die Installer, zuletzt `releases.json`, und prüft danach online Signatur und Erreichbarkeit. Bricht die Verbindung ab, wird neu verbunden und ab der Abbruchstelle fortgesetzt; manuell geht das mit `python tools/release.py upload`. Weitere Befehle: `check-online` und `status`. Die Server-Einrichtung steht in [server-einrichtung.md](server-einrichtung.md). Schlüssel liegen unter `~/.akustikmess/` (Signatur- und Upload-Schlüssel), **beide sichern**.

**Eigener Server:** Jeder Webspace, jedes NAS mit Webserver oder ein statisches Hosting (z. B. GitHub Pages, Netlify, Cloudflare Pages) funktioniert, solange es per https erreichbar ist. Der Veröffentlichungsordner wird 1:1 hochgeladen.

**Dropbox:**
1. `configure --mode dropbox --publish-dir "<Dropbox-Ordner>"` ausführen.
2. Dropbox zeigt keine Webseiten an. Geteilt werden deshalb die Freigabelinks der Dateien, nicht `index.html`.
3. Nach dem ersten Release in Dropbox je einen Freigabelink für `releases.json` und die Installer (`stable/…`, `beta/…`) erstellen.
4. Die Links in `release_config.json` → `dropbox_links` eintragen, dann `configure` erneut und `relink` ausführen.
5. Die Dateinamen bleiben je Kanal gleich, damit die Links beim Überschreiben gültig bleiben. Versionierte Kopien liegen in `archiv/`.

**macOS-Installer:** Baut GitHub Actions bei jedem Release mit (`publish --platform windows --platform macos` übernimmt ihn). Alternativ auf einem Mac: `tools/build_macos.sh`, dann `release.py add-asset --platform macos --file …`.

**Verteilung als ZIP-Bundle:** Je System entsteht `AkustikMess-<Version>-Windows.zip` bzw. `-macOS.zip` mit dem
Programmordner, einem Startskript (entfernt die Download-Markierung für den eigenen Ordner) und LIESMICH. Installer
(Inno Setup, pkg) sind noch vorhanden (`build --stage installer`), aber erst mit eigenem Code-Signing-Zertifikat
sinnvoll – unsignierte Installer blockiert Smart App Control.

**Privates Repository:** `publish` braucht einen GitHub-Zugangsschlüssel mit Leserecht. Einmalig auf GitHub unter
*Settings → Developer settings → Personal access tokens → Fine-grained tokens* einen Token nur für
`Kulow00/AkustikMess` mit **Contents: Read-only** anlegen und speichern:

```bash
python tools/release.py github-token
```

**GitHub-Minuten:** Private Repositories haben im kostenlosen Plan 2.000 Minuten/Monat; macOS zählt zehnfach.
Ein Release kostet etwa 20 (Windows) + 10×10 (macOS) ≈ 120 Minuten, ein Push mit Tests etwa 5 Minuten.
