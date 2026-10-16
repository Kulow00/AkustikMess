# Lizenzserver und Homepage einrichten (nur für den Projektinhaber)

Voraussetzung: [server-einrichtung.md](server-einrichtung.md) ist erledigt (Domain, Caddy, Upload).
Alle Befehle auf dem Server als Benutzer mit `sudo`.

## 1. Schlüssel am Laptop

```bash
python tools/licenses.py keygen-root
```

Erzeugt `~/.akustikmess/license_root_key.pem` (offline, darf alle Lizenzarten ausstellen) und trägt den
öffentlichen Teil in `akustik/license_config.py` ein. **Mit den anderen Schlüsseln sichern.**

## 2. Lizenzserver auf dem Server starten

```bash
sudo mkdir -p /srv/akmess/license/data
cd /srv/akmess/license
sudo git clone https://github.com/NAME/akustikmess.git src
sudo cp src/server/docker-compose.yml src/server/.env.example .
sudo mv .env.example .env && sudo chmod 600 .env
sudo chown 10001 data && sudo chmod 700 data
docker network ls                       # Netzwerk des Caddy-Containers heraussuchen
sudo nano docker-compose.yml            # CADDY_NETZWERK ersetzen
sudo nano .env                          # SMTP-Zugang eintragen (oder leer lassen, siehe unten)
docker compose run --rm license python license_server.py keygen
docker compose up -d --build
docker logs akmess-license
```

`keygen` gibt den **öffentlichen** Schlüssel des Servers aus. Am Laptop eintragen:

```bash
python tools/licenses.py set-server-key --public <SCHLÜSSEL>
```

**Ohne SMTP** zeigt die Webseite den Schlüssel sofort an, prüft aber die E-Mail-Adresse nicht. Für echte
Registrierungen SMTP eintragen (z. B. das Postfach deines Mail-Anbieters; Port 587 mit STARTTLS oder 465).

## 3. Caddy: Lizenzserver und Sicherheits-Header

Den Block `akmess.alex-kulow.de { … }` im Caddyfile ersetzen durch:

```
akmess.alex-kulow.de {
	encode zstd gzip
	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options nosniff
		X-Frame-Options DENY
		Referrer-Policy strict-origin-when-cross-origin
		Permissions-Policy "camera=(), microphone=(), geolocation=()"
		Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
		-Server
	}
	handle /api/* {
		reverse_proxy akmess-license:8080
	}
	handle {
		root * /srv/akmess
		file_server
		@manifest path /releases.json
		header @manifest Cache-Control "no-cache"
		@installer path *.exe *.pkg
		header @installer Content-Disposition attachment
		@partial path *.part
		respond @partial 404
	}
}
```

Prüfen und übernehmen wie in server-einrichtung.md (`caddy validate`, dann neu laden):

```bash
docker exec caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
curl -s https://akmess.alex-kulow.de/api/health
```

Ausgabe `{"ok": true}` = Lizenzserver erreichbar.

## 4. Impressum, Datenschutz, Registrierung einschalten

In `release_config.json` am Laptop ergänzen:

```json
"site": {
  "owner_name": "Alex Kulow",
  "owner_address": "Straße Nr.\nPLZ Ort",
  "owner_email": "kontakt@alex-kulow.de",
  "mail_provider": "<Name des Mail-Anbieters>",
  "registration": true
}
```

Dann Homepage neu bauen und hochladen:

```bash
python tools/release.py site
```

Die Registrierung erscheint erst, wenn alle Impressum-Angaben gesetzt sind. Die Texte für Datenschutz und
Impressum sind Vorlagen – bitte einmal prüfen (lassen).

## 5. Neues Release

Die Lizenzschlüssel gelten im Programm erst ab dem nächsten Release (die öffentlichen Schlüssel werden in das
Programm eingebaut). Danach zeigt AkustikMess „Kostenlos registrieren“ in der Statusleiste und Hilfe → Lizenz….

## Verwaltung

| Aufgabe | Befehl |
|---|---|
| Registrierungen ansehen | `docker exec akmess-license python license_server.py list --search TEXT` |
| Statistik | `docker exec akmess-license python license_server.py stats` |
| Lizenz sperren | `docker exec akmess-license python license_server.py revoke L-XXXX --reason "…"` |
| Sperre aufheben | `docker exec akmess-license python license_server.py unrevoke L-XXXX` |
| Daten löschen (DSGVO) | `docker exec akmess-license python license_server.py delete --email a@b.de` |
| Pro-/Testlizenz ausstellen | am Laptop: `python tools/licenses.py issue --name … --email … --plan pro --updates-years 1` |
| Eigene Lizenzen anzeigen | am Laptop: `python tools/licenses.py list` |

**Sicherung:** `/srv/akmess/license/data` (Datenbank + Serverschlüssel) in die Server-Sicherung aufnehmen.
Geht der Serverschlüssel verloren: neuen erzeugen, `set-server-key` am Laptop, neues Release – bereits
ausgestellte Community-Lizenzen müssen dann neu ausgestellt werden.
