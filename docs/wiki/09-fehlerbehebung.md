# Häufige Probleme

## Windows: „Smart App Control hat eine App blockiert“

AkustikMess ist (noch) nicht digital signiert. Windows markiert heruntergeladene Dateien; Smart App Control blockiert
markierte, unsignierte Programme. **„AkustikMess starten.bat“** entfernt diese Markierung für den AkustikMess-Ordner.
Blockiert Windows trotzdem: Ordner löschen, **Rechtsklick auf die heruntergeladene ZIP-Datei → Eigenschaften → unten
„Zulassen“ anhaken → OK**, dann erneut entpacken. Die entpackten Dateien sind dann nicht mehr markiert.

## Windows: „Der Computer wurde durch Windows geschützt“

SmartScreen kennt eine neue Version noch nicht: **Weitere Informationen → Trotzdem ausführen**.

## macOS: „kann nicht geöffnet werden, da der Entwickler nicht verifiziert werden kann“

**Systemeinstellungen → Datenschutz & Sicherheit** → ganz unten **„Dennoch öffnen“**.

## Kein Eingangssignal

- **macOS:** Systemeinstellungen → Datenschutz & Sicherheit → **Mikrofon** → AkustikMess erlauben.
- **Windows:** Einstellungen → Datenschutz → **Mikrofon** → Desktop-Apps Zugriff erlauben.
- Richtigen Eingang und Phantomspeisung (48 V) am Interface prüfen.

## Übertragungsfunktion bleibt unruhig

- **Laufzeit finden** erneut ausführen.
- Kohärenz prüfen: Störgeräusche oder starker Hall senken sie.
- Generatorpegel erhöhen, aber die Pegelgrenze beachten.

## Handy erreicht die Fernbedienung nicht

- Gleiches WLAN? Gäste-WLANs trennen Geräte oft voneinander.
- Firewall-Abfrage unter Windows für „Private Netzwerke“ erlaubt?
- VPN am Rechner trennen oder im Dialog die WLAN-Adresse wählen.

## Fehler melden

Nicht gelöst? Bitte auf GitHub melden (Link „Fehler melden“ unten auf jeder Seite) – mit Betriebssystem,
AkustikMess-Version (Hilfe → Über AkustikMess), Audio-Interface und den Schritten, die zum Fehler führen.
