# Konzept: Lizenzsystem, Homepage und Sicherheit

Stand: 16.10.2026 · nur für den Projektinhaber

## Ziel

1. **Jetzt:** Jede neue Installation kann sich kostenlos registrieren und bekommt einen persönlichen
   Lizenzschlüssel. So entsteht ein Nutzerstamm mit Kontaktmöglichkeit.
2. **Später (optional):** Dieselbe Technik trägt kostenpflichtige Lizenzen (Pro, Testversion, Abo oder Kauf mit
   Update-Zeitraum), ohne dass bestehende Nutzer etwas neu installieren müssen.
3. **Immer:** Datenschutzfreundlich (Prüfung offline, keine Telemetrie) und sicher (gefälschte Lizenzen sind
   kryptografisch ausgeschlossen).

## Bausteine

```
 Laptop (offline)                         Server akmess.alex-kulow.de                Nutzer
 ───────────────                          ──────────────────────────                 ──────
 Root-Schlüssel ──► Pro-/Testlizenzen ─────────────── per E-Mail ──────────────────► Programm
 tools/licenses.py                        Caddy (HTTPS, Sicherheits-Header)            │ prüft offline
                                          ├─ Homepage, Wiki, Download (statisch)       │ (Ed25519)
                                          └─ /api → Lizenzserver (Docker)  ◄── Formular ┘
                                               Server-Schlüssel ─► Community-Lizenzen
                                               SQLite: Name, E-Mail, Status
                                               /api/revocations (signierte Sperrliste) ─► Programm
```

### Lizenzschlüssel

`AKM1.<Nutzdaten>.<Signatur>` – Nutzdaten (JSON): Lizenz-ID, Name, E-Mail, Plan, Funktionen, Ausstellungsdatum,
optional Ablaufdatum (`expires`) und Update-Zeitraum (`updates_until`). Signiert mit Ed25519.

| Aussteller | Wo | Darf ausstellen |
|---|---|---|
| **root** | nur auf deinem Laptop (`~/.akustikmess/license_root_key.pem`) | alle Pläne |
| **server** | im Lizenzserver-Container | nur `community` |

Wird der Server kompromittiert, kann ein Angreifer höchstens kostenlose Community-Lizenzen erzeugen oder Lizenzen
sperren – **niemals Bezahl-Lizenzen**. Das Programm lehnt Pro-Lizenzen mit Server-Signatur ab.

### Pläne und Durchsetzung

| Plan | Heute | Später möglich |
|---|---|---|
| community | kostenlos, alle Funktionen | bleibt kostenlos |
| trial | – | z. B. 30 Tage alle Pro-Funktionen |
| pro | – | Zusatzfunktionen, `licenses.has("pro")` im Code |

Wie streng ein Build ist, steht in `akustik/license_config.py` → `ENFORCEMENT`:

- `off` – keine Lizenzfunktionen
- **`remind` (aktuell)** – alles nutzbar, Hinweis „Kostenlos registrieren“ in der Statusleiste
- `required` – ohne gültige Lizenz startet keine Messung (der Dialog öffnet sich beim Start)

Kauflizenzen mit `updates_until` gelten für alle Versionen, die bis zu diesem Datum erschienen sind (das
Erscheinungsdatum schreibt das Release-Werkzeug in `akustik/__init__.py`). Ältere Versionen laufen unbegrenzt
weiter – faires Modell ähnlich vieler Audio-Programme.

### Sperren

Der Lizenzserver veröffentlicht eine signierte Sperrliste. Das Programm lädt sie zusammen mit der Update-Suche
(nur nach Zustimmung). Offline-Nutzer werden nie ausgesperrt; eine Sperre wirkt beim nächsten Online-Check.

### Registrierung (Datenfluss)

1. Formular auf `registrieren.html`: Name, E-Mail, Einwilligung (Pflicht), verstecktes Honigtopf-Feld gegen Bots.
2. `POST /api/register` → Bestätigungs-E-Mail mit Einmal-Link (48 h gültig, nur Hash gespeichert).
3. Klick → Lizenz wird ausgestellt, angezeigt und per E-Mail zugeschickt.
4. Erneute Registrierung mit derselben Adresse → vorhandener Schlüssel wird noch einmal geschickt. Die Antwort
   ist in beiden Fällen gleich, damit niemand herausfinden kann, ob eine Adresse registriert ist.

Ohne SMTP-Konfiguration wird der Schlüssel sofort angezeigt (ohne E-Mail-Prüfung) – praktisch für den Start.

## Homepage

Statisch erzeugt von `tools/site.py` (Befehl `python tools/release.py site`), automatisch bei jedem Release:

| Seite | Inhalt |
|---|---|
| Startseite | Funktionen, Download mit OS-Erkennung, Stabil/Beta, Patch Notes, Fehler melden |
| Wiki | aus `docs/wiki/*.md` – auch auf GitHub lesbar, eine Quelle für beides |
| Lizenz | Registrierung und Lizenzarten |
| Datenschutz, Impressum | Vorlagen mit deinen Angaben aus `release_config.json` |

Ohne vollständige Impressum-Angaben bleibt die Registrierung automatisch aus (kein Datensammeln ohne
Datenschutzerklärung).

## Sicherheit

| Bereich | Maßnahme |
|---|---|
| Lizenzen | Ed25519-Signaturen, zwei Aussteller mit getrennten Rechten, Root-Schlüssel nur offline |
| Updates | signiertes `releases.json` (eigener Schlüssel) + SHA-256 je Datei + Windows-Code-Signatur (SignPath) |
| Webseite | nur HTTPS mit HSTS, strenge Content-Security-Policy (kein Inline-JavaScript, keine Fremd-Inhalte), X-Frame-Options, kein Tracking |
| Lizenzserver | kein offener Port (nur über Caddy), läuft als Nicht-root, Dateisystem schreibgeschützt, alle Rechte entzogen, 256 MB Speicher; Anfragen max. 4 KB, nur JSON; Ratenbegrenzung je IP und je E-Mail; keine Admin-Schnittstelle im Netz (Verwaltung nur per `docker exec`) |
| Daten | nur Name + E-Mail + Zeitstempel; keine IP-Adressen gespeichert; unbestätigte Anfragen nach 48 h gelöscht; Löschbefehl für DSGVO-Anfragen |
| Upload | SFTP nur mit Schlüssel, festgelegter Host-Schlüssel, chroot-Benutzer ohne Shell |
| Schlüssel | alle privaten Schlüssel in `~/.akustikmess` (Laptop) bzw. `/srv/akmess/license/data` (Server); nie im Repository |

## Wichtig: Open Source und Bezahlmodell

AkustikMess steht unter der **GPL-3.0**. Das bedeutet für ein späteres Bezahlmodell:

- **Erlaubt und üblich:** offizielle Installer, Support, Schulungen oder Zusatzfunktionen gegen Geld anbieten.
- **Nicht verhinderbar:** Wer den Quellcode nimmt, kann die Lizenzprüfung entfernen und eine eigene Fassung bauen
  (muss diese aber wieder unter der GPL veröffentlichen). Die Lizenzprüfung ist bei Open Source eine
  Erinnerung und ein Komfort, kein Kopierschutz.
- **Dein Spielraum als Urheber:** Du kannst künftige Versionen oder Zusatzmodule unter einer anderen Lizenz
  veröffentlichen (dafür sorgt CONTRIBUTING.md bei fremden Beiträgen). Bereits veröffentlichte Versionen bleiben
  dauerhaft GPL.
- **SignPath Foundation:** Die kostenlose Signatur gilt für Open-Source-Projekte. Vor einem Bezahlmodell bei
  SignPath nachfragen, ob das Projekt so weiter gefördert wird – sonst wird ein eigenes Zertifikat nötig
  (ca. 100–250 €/Jahr).

Empfohlener Weg, falls es kostenpflichtig werden soll: **Open-Core** – die Messsoftware bleibt GPL und kostenlos,
Pro-Funktionen (z. B. Mehrkanal-Messung, Berichte, Projektverwaltung) kommen als separates, nicht-öffentliches
Modul, das per `licenses.has("pro")` freigeschaltet wird.

## Fahrplan

| Phase | Inhalt | Status |
|---|---|---|
| 1 | Lizenzprüfung im Programm, Werkzeug, Lizenzserver, Homepage mit Wiki, Datenschutz/Impressum | **gebaut, getestet** |
| 2 | Server einrichten (docs/lizenzserver-einrichtung.md), Impressum-Angaben, Registrierung einschalten, Release | offen – deine Schritte |
| 3 | Bezahlweg (z. B. Rechnung/Überweisung, später Shop mit automatischer Ausstellung per Webhook) | bei Bedarf |
| 4 | Optional: Aktivierungen je Rechner zählen (Online-Aktivierung) | bei Bedarf, mit Datenschutz-Abwägung |
