"""Lizenz-Einstellungen dieses Builds. Die Schlüssel trägt ``tools/licenses.py keygen`` ein.

Zwei Aussteller, damit ein kompromittierter Webserver keine Bezahl-Lizenzen fälschen kann:

* ``root``   – offline auf dem Rechner des Projektinhabers, darf alle Pläne ausstellen
* ``server`` – auf dem Lizenzserver (kostenlose Registrierung), darf nur ``SERVER_PLANS``
"""

# Öffentliche Ed25519-Schlüssel (Base64). Leer = Aussteller nicht eingerichtet.
ROOT_PUBLIC_KEY = "3noY7S+nGCDG7uyWN+ghKhKvbWEbqQ69x9NTYCo347g="
SERVER_PUBLIC_KEY = "pXmPFyTv9x/dMffuh2PlvEpQCLRQ9ohPDhvQqGUQua4="

# Pläne, die der Lizenzserver selbstständig ausstellen darf
SERVER_PLANS = ("community",)

# Wie streng dieser Build ist:
#   "off"      – keine Lizenzfunktionen sichtbar
#   "remind"   – alles nutzbar, Hinweis „kostenlos registrieren“ (aktueller Stand)
#   "required" – ohne gültige Lizenz startet keine Messung
ENFORCEMENT = "remind"

# Webseite mit Registrierung und Sperrliste
SITE_URL = "https://akmess.alex-kulow.de"
REGISTER_URL = SITE_URL + "/registrieren.html"
REVOCATIONS_URL = SITE_URL + "/api/revocations"
# Öffentliches Repository nur für Fehlermeldungen und Ideen (der Quellcode ist privat)
FEEDBACK_URL = "https://github.com/Kulow00/AkustikMess-Feedback/issues/new/choose"
