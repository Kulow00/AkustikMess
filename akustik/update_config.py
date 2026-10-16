"""Update-Einstellungen, die beim Erstellen eines Releases eingetragen werden
(``tools/release.py keygen`` bzw. ``configure``). Nicht von Hand ändern."""

# Adresse des signierten Release-Verzeichnisses (releases.json)
MANIFEST_URL = "https://akmess.alex-kulow.de/releases.json"

# Öffentlicher Ed25519-Schlüssel (Base64) zum Prüfen der Release-Signatur
PUBLIC_KEY = "prb9p6CinbAAP51IJQnkyZNyRLeG/7CDkvbjotvlfzQ="
