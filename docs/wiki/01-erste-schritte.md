# Erste Schritte

## Installieren

- **Windows 10/11:** Installer von der Download-Seite laden und starten. Es werden keine Administratorrechte benötigt.
- **macOS:** `.pkg`-Datei öffnen. Beim ersten Start blockiert macOS das Programm, weil es nicht über das
  Apple-Entwicklerprogramm beglaubigt ist: **Systemeinstellungen → Datenschutz & Sicherheit → „Dennoch öffnen“**.
  Danach den Mikrofonzugriff erlauben.

Beim ersten Start fragt AkustikMess, ob es automatisch nach Updates suchen darf. Ohne Zustimmung baut das
Programm keine Verbindung ins Internet auf.

## Ohne Hardware ausprobieren

1. **Audio-Einstellungen…** → Eingabegerät **„Simulation (ohne Hardware)“**.
2. **▶ Audio starten** (Leertaste), dann **Generator EIN** (Taste G).
3. Im Modus **Echtzeit** auf **Laufzeit finden** klicken – die Übertragungsfunktion eines simulierten
   Lautsprechers im Raum erscheint.

Die Simulation enthält einen virtuellen Raum mit etwa 1 s Nachhall und eine Loopback-Referenz. Alle Funktionen
lassen sich damit ausprobieren.

## Die drei Modi

| Modus | Wofür | Taste |
|---|---|---|
| [Echtzeit](echtzeit.html) | Spektrum und Übertragungsfunktion: entzerren, ausrichten, vergleichen | 1 |
| [Impulsantwort](impulsantwort.html) | Nachhallzeit, Deutlichkeit, STI | 2 |
| [SPL](spl.html) | Schallpegel überwachen und protokollieren | 3 |

## Tastenkürzel

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
| F1 | Übersicht aller Kürzel |

Sitzungen (`.akmess`) enthalten alle Kurven, Einstellungen und Notizen. AkustikMess sichert jede Minute
automatisch und bietet nach einem Absturz die Wiederherstellung an.

Weiter mit dem [Messaufbau](messaufbau.html).
