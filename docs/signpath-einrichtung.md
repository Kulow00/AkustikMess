# Kostenlose Code-Signatur einrichten (GitHub + SignPath Foundation)

Ziel: Windows (Smart App Control, SmartScreen) vertraut dem Installer, weil er mit dem Zertifikat der
SignPath Foundation signiert ist. Das kostet nichts, setzt aber ein öffentliches Open-Source-Projekt
voraus. Der Ablauf danach ist fast derselbe wie bisher, nur dass GitHub baut und signiert.

```
release.py release  →  Tag v1.2.3 auf GitHub  →  GitHub Actions: Tests, Build
        →  SignPath signiert (du gibst frei)  →  GitHub-Release mit Installern
release.py publish --wait  →  Installer holen, Signatur prüfen, releases.json signieren, SFTP-Upload
```

## 1. GitHub-Repository anlegen (einmalig)

1. Auf GitHub ein **öffentliches** Repository anlegen, z. B. `akustikmess` – ohne README/Lizenz
   (beides ist schon im Projekt).
2. **Zwei-Faktor-Anmeldung** für dein GitHub-Konto einschalten (Pflicht für SignPath).
3. Im Projektordner (Git-Identität einmalig setzen; als E-Mail am besten die
   „noreply“-Adresse aus GitHub → Settings → Emails, damit deine echte Adresse nicht öffentlich wird):

   ```
   git config user.name "Dein Name"
   git config user.email "ID+NAME@users.noreply.github.com"
   git add -A
   git commit -m "AkustikMess als Open Source"
   git branch -M main
   git remote add origin https://github.com/NAME/akustikmess.git
   git push -u origin main
   ```

4. Dem Release-Werkzeug das Repository mitteilen:

   ```
   python tools/release.py configure-github --repo NAME/akustikmess
   ```

Ab jetzt laufen bei jedem Push die Tests auf GitHub (Windows und macOS).

## 2. Ein erstes, noch unsigniertes Release

SignPath nimmt nur Projekte an, die schon veröffentlicht sind. Deshalb zuerst ein normales Release
(GitHub baut dann ohne Signatur, weil noch kein SignPath-Token hinterlegt ist):

```
python tools/release.py release --channel beta
```

Unter *Actions* auf GitHub den Lauf „Release“ beobachten. Am Ende gibt es unter *Releases* die
Version mit Windows- und macOS-Installer. **Nicht** mit `publish` auf akmess.alex-kulow.de bringen –
der Installer ist ja noch unsigniert.

## 3. Bei der SignPath Foundation bewerben

Formular: https://signpath.org/apply – dort angeben:

- Repository-Adresse, Lizenz **GPL-3.0-or-later**, kurze Beschreibung (Messsoftware für Beschallung und Raumakustik)
- Download-Seite: https://akmess.alex-kulow.de
- Code-Signing-Richtlinie: `docs/code-signing-policy.md` (im README verlinkt)

Die Prüfung dauert in der Regel einige Tage bis wenige Wochen. Danach bekommst du Zugang zu
https://app.signpath.io.

## 4. SignPath einrichten (nach der Zusage)

In https://app.signpath.io (Zwei-Faktor-Anmeldung einschalten):

1. **Project** mit dem Slug `akustikmess` – mit dem GitHub-Repository als „Trusted Build System“
   verknüpfen (SignPath führt durch die Installation der GitHub-App).
2. **Artifact Configurations** im Projekt anlegen und den Inhalt der Dateien einfügen:
   - Slug `app` ← `.signpath/artifact-configurations/app.xml`
   - Slug `installer` ← `.signpath/artifact-configurations/installer.xml`
3. **Signing Policy** `release-signing` (legt die Foundation meist schon an) – du als *Approver*.
4. Unter deinem Benutzer einen **API-Token** (CI User) erzeugen, der für das Projekt einreichen darf.

Auf GitHub im Repository unter *Settings → Secrets and variables → Actions*:

| Art | Name | Wert |
|---|---|---|
| Secret | `SIGNPATH_API_TOKEN` | der API-Token aus SignPath |
| Variable | `SIGNPATH_ORGANIZATION_ID` | Organisations-ID aus SignPath (Settings) |
| Variable (nur falls abweichend) | `SIGNPATH_PROJECT_SLUG` | Standard `akustikmess` |
| Variable (nur falls abweichend) | `SIGNPATH_SIGNING_POLICY_SLUG` | Standard `release-signing` |

## 5. Ab jetzt: jede Veröffentlichung

1. Änderungen in `CHANGELOG.md` unter `[Unreleased]` eintragen, alles committen.
2. `python tools/release.py release --channel beta` (oder `stable`)
3. SignPath schickt **zwei Freigabe-Anfragen** (Programmdatei, dann Installer). Jeweils in SignPath
   prüfen, dass sie zum gerade gepushten Tag gehören, und *Approve* klicken.
4. `python tools/release.py publish --wait`
   – wartet auf das GitHub-Release, lädt den Installer, prüft Prüfsumme und **Signatur**
   (unsignierte Installer werden abgelehnt), signiert `releases.json` mit deinem Update-Schlüssel und
   lädt alles per SFTP auf akmess.alex-kulow.de. Mit `--platform windows --platform macos` wartet es
   zusätzlich auf den macOS-Installer.

Der Update-Schlüssel (`~/.akustikmess/release_signing_key.pem`) und der Upload-Schlüssel bleiben
dabei auf deinem Rechner – sie gehören **nie** ins Repository oder zu GitHub.

## Hinweise

- **Smart App Control** blockiert nur heruntergeladene, nicht signierte Dateien. Mit signiertem
  Installer läuft die Installation; Programm-Updates lädt AkustikMess selbst herunter.
- **SmartScreen** kann bei einem neuen Zertifikat anfangs trotzdem „Unbekannte App“ melden, bis
  genügend Downloads bekannt sind. Das verschwindet von allein.
- **macOS** bleibt vorerst unsigniert (dafür bräuchte es das Apple-Entwicklerprogramm).
- Ohne gesetztes `SIGNPATH_API_TOKEN` baut der Workflow weiter, nur unsigniert.
