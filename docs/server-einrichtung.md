# Server einrichten: akmess.alex-kulow.de

Annahmen: Debian/Ubuntu-Server, Befehle als Benutzer mit `sudo`. Der Upload-Benutzer
`akmess-deploy` darf **nur per SFTP** und **nur in seinen Ordner** schreiben (chroot).
Die Web-Wurzel der Domain ist `/srv/akmess/www`.

## 0. DNS (beim Domain-Anbieter)

`A`-Eintrag `akmess` → IPv4 des Servers (bei IPv6 zusätzlich `AAAA`). Prüfen:

```bash
dig +short akmess.alex-kulow.de
```

## 1. Benutzer und Ordner

```bash
sudo useradd --system --user-group --home-dir /srv/akmess --shell /usr/sbin/nologin akmess-deploy
sudo mkdir -p /srv/akmess/www
sudo chown root:root /srv/akmess && sudo chmod 755 /srv/akmess          # chroot-Wurzel muss root gehören
sudo chown akmess-deploy:www-data /srv/akmess/www && sudo chmod 2755 /srv/akmess/www
```

## 2. Upload-Schlüssel eintragen

```bash
sudo mkdir -p /etc/ssh/authorized_keys
echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKn4KMdDPYovSC6siCeQOUSyE8YcNdTwkGgEUK5AtQUp akmess-deploy@Sir-Lap-A-Lot' \
  | sudo tee /etc/ssh/authorized_keys/akmess-deploy
sudo chmod 644 /etc/ssh/authorized_keys/akmess-deploy
```

## 3. SSH: nur SFTP, nur Schlüssel, eingesperrt in /srv/akmess

Der Block muss **ans Ende** von `/etc/ssh/sshd_config`:

```bash
sudo tee -a /etc/ssh/sshd_config >/dev/null <<'EOF'

# --- AkustikMess-Uploads ---
Match User akmess-deploy
    AuthorizedKeysFile /etc/ssh/authorized_keys/%u
    PasswordAuthentication no
    ChrootDirectory /srv/akmess
    ForceCommand internal-sftp -u 0022
    AllowTcpForwarding no
    X11Forwarding no
    PermitTunnel no
EOF
sudo sshd -t && sudo systemctl reload ssh
```

`sshd -t` prüft die Konfiguration vor dem Neuladen. Gibt es ein `AllowUsers` in der `sshd_config`,
muss `akmess-deploy` dort ergänzt werden. Eine **bestehende SSH-Sitzung offen lassen**, bis der Test
in Schritt 6 geklappt hat.

## 4. Webserver: Caddy (läuft bei diesem Server als Docker-Container vor Nextcloud)

Caddy liefert den Ordner selbst aus und holt das HTTPS-Zertifikat automatisch.
**Kein Apache/Nginx installieren**: Ports 80/443 gehören dem Caddy-Container.

### 4a. Pfade herausfinden

```bash
docker inspect caddy --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}'
docker inspect caddy --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'
```

Die erste Zeile ist der Ordner mit der `docker-compose.yml` (bzw. `compose.yaml`), die zweite zeigt,
wo das `Caddyfile` auf dem Server liegt (Zeile mit `-> /etc/caddy/Caddyfile`).

### 4b. Sicherung

```bash
cd <Compose-Ordner aus 4a>
cp docker-compose.yml docker-compose.yml.bak-$(date +%F)
cp <Caddyfile-Pfad aus 4a> <Caddyfile-Pfad aus 4a>.bak-$(date +%F)
```

### 4c. Ordner in den Caddy-Container einbinden (nur lesend)

In `docker-compose.yml` beim Dienst `caddy` unter `volumes:` eine Zeile ergänzen
(gleiche Einrückung wie die vorhandenen Einträge):

```yaml
      - /srv/akmess/www:/srv/akmess:ro
```

### 4d. Domain im Caddyfile ergänzen

```bash
tee -a <Caddyfile-Pfad aus 4a> >/dev/null <<'EOF'

akmess.alex-kulow.de {
	root * /srv/akmess
	file_server
	@manifest path /releases.json
	header @manifest Cache-Control "no-cache"
	@installer path *.exe *.pkg
	header @installer Content-Disposition attachment
	@partial path *.part
	respond @partial 404
}
EOF
```

### 4e. Prüfen und übernehmen

```bash
docker exec caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose up -d caddy
docker logs caddy --tail 40
```

Nur wenn `validate` „Valid configuration“ meldet, `docker compose up -d caddy` ausführen. Das erstellt
den Caddy-Container mit dem neuen Ordner neu (Nextcloud ist dabei nur wenige Sekunden nicht
erreichbar). Im Log sollte kurz darauf `certificate obtained successfully` für `akmess.alex-kulow.de`
stehen. Das klappt erst, wenn der DNS-Eintrag aus Schritt 0 wirkt.

**Rückweg bei Problemen:** die `.bak`-Dateien zurückkopieren und `docker compose up -d caddy`.

## 5. Test

```bash
echo ok | sudo tee /srv/akmess/www/test.txt >/dev/null
curl -s https://akmess.alex-kulow.de/test.txt
sudo rm /srv/akmess/www/test.txt
```

Ausgabe `ok` = Domain, Zertifikat und Ordner funktionieren.

## 6. Fingerabdruck des Servers (für die Bestätigung am Laptop)

```bash
for f in /etc/ssh/ssh_host_*_key.pub; do ssh-keygen -lf "$f"; done
```

Danach am Laptop:

```bash
python tools/release.py sftp-setup --host <server> --port <port> --user akmess-deploy --remote-dir /www
```

`/www` ist der Pfad **innerhalb** des chroot (= `/srv/akmess/www` auf dem Server).
