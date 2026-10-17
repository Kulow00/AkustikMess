# Erste Schritte

## Installieren

AkustikMess ist kostenlos; zum Herunterladen brauchst du eine persönliche Lizenz ([Lizenz anfragen](lizenz.html)).
Nach der Freigabe kommt ein Download-Link per E-Mail, der die passende ZIP-Datei für dein System anbietet –
keine Installation, keine Administratorrechte.

- **Windows 10/11:** ZIP entpacken (Rechtsklick → „Alle extrahieren“), den Ordner **AkustikMess** an einen festen Platz
  legen (z. B. *Dokumente*) und **„AkustikMess starten.bat“** doppelklicken. Fragt Windows nach, „Ausführen“ wählen.
  Tipp: Rechtsklick auf die .bat → „Verknüpfung erstellen“ und die Verknüpfung auf den Desktop ziehen.
- **macOS:** ZIP öffnen, den Ordner **AkustikMess** z. B. in *Programme* legen. Beim ersten Mal
  **Rechtsklick auf „AkustikMess starten.command“ → Öffnen → Öffnen** (AkustikMess ist nicht von Apple beglaubigt,
  ein Doppelklick wird deshalb beim ersten Mal blockiert). Danach den Mikrofonzugriff erlauben.

Updates lädt AkustikMess selbst und tauscht dabei die Programmdateien im Ordner aus.

Beim ersten Start fragt AkustikMess, ob es automatisch nach Updates suchen darf. Ohne Zustimmung baut das
Programm keine Verbindung ins Internet auf.

## Ohne Hardware ausprobieren

1. **Audio-Einstellungen…** → Eingabegerät **„Simulation (ohne Hardware)“**.
2. **▶ Audio starten** (Leertaste), dann **Generator EIN** (Taste G).
3. Im Modus **Echtzeit** auf **Laufzeit finden** klicken – die Übertragungsfunktion eines simulierten
   Lautsprechers im Raum erscheint.

Die Simulation enthält einen virtuellen Raum mit etwa 1 s Nachhall und eine Loopback-Referenz. Alle Funktionen
lassen sich damit ausprobieren.

## Die vier Modi

| Modus | Wofür | Taste |
|---|---|---|
| [Echtzeit](echtzeit.html) | Spektrum und Übertragungsfunktion: entzerren, ausrichten, vergleichen | 1 |
| [Impulsantwort](impulsantwort.html) | Nachhallzeit, Deutlichkeit, STI | 2 |
| [SPL](spl.html) | Schallpegel überwachen und protokollieren | 3 |
| [Raum](raum.html) | Lautsprecher planen, Pegelkarte, Sub-Setups, Messpunkte | 4 |

## Tastenkürzel

| Taste | Funktion |
|---|---|
| Leertaste | Audio starten/stoppen |
| G / M | Generator ein/aus · sofort stumm |
| S / Umschalt+S | Übertragungsfunktion / Spektrum speichern |
| D · R · P | Laufzeit finden · Mittelung zurücksetzen · Spitzenwert halten |
| Eingabe | Impulsantwort messen |
| N | SPL-Notiz eingeben |
| 1 / 2 / 3 / 4 | Modus wechseln |
| Strg+N/O/S | Sitzung neu/öffnen/speichern |
| F1 | Übersicht aller Kürzel |

Sitzungen (`.akmess`) enthalten alle Kurven, Einstellungen und Notizen. AkustikMess sichert jede Minute
automatisch und bietet nach einem Absturz die Wiederherstellung an.

Weiter mit dem [Messaufbau](messaufbau.html).
