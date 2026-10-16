# Code signing policy / Richtlinie zur Code-Signatur

Free code signing provided by [SignPath.io](https://about.signpath.io/), certificate by
[SignPath Foundation](https://signpath.org/).

*Kostenlose Code-Signatur durch SignPath.io, Zertifikat der SignPath Foundation.*

## What is signed / Was signiert wird

- `AkustikMess.exe` (the program) and `AkustikMess-<version>-Windows-Setup.exe` (the installer).
- Only binaries built from this repository by the GitHub Actions workflow
  [`.github/workflows/release.yml`](../.github/workflows/release.yml) for a release tag `v*` are
  submitted for signing. Nothing is signed from a local build.
- Third-party libraries bundled by PyInstaller are not signed by this project.

## Team roles / Rollen

| Role | Members |
|---|---|
| Committers and reviewers | Alex Kulow (project owner) |
| Approvers (approve each signing request in SignPath) | Alex Kulow |

All team members use multi-factor authentication for GitHub and SignPath.
Every signing request is approved manually after checking that it belongs to a tagged release.

## Privacy policy / Datenschutz

This program will not transfer any information to other networked systems unless specifically
requested by the user or the person installing or operating it.

- **Update check:** only after the user agrees at first start (or enables it under
  *Hilfe → Nach Updates suchen…*). The program then downloads the public, signed release list
  `releases.json` from the configured update server. No personal data, measurement data or
  identifiers are sent.
- **Remote control (phone/tablet):** off by default. When the user switches it on, the program
  accepts connections from devices in the local network that know the one-time access token shown
  in the program. Nothing is sent to the internet.
- **Measurements and sessions** are stored only locally on the user's computer.

*Das Programm überträgt keine Informationen an andere Systeme, außer der Nutzer veranlasst es ausdrücklich.
Die Update-Suche läuft erst nach Zustimmung beim ersten Start und lädt nur die öffentliche, signierte
Versionsliste. Die Fernbedienung ist standardmäßig aus und arbeitet nur im lokalen Netzwerk.*

## Reporting / Meldungen

Problems with a signed release (e.g. a suspected compromised build) can be reported via the
GitHub issues of this repository or to SignPath Foundation (https://signpath.org/).
