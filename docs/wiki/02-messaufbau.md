# Messaufbau und Audio-Interface

## Was du brauchst

- Ein **Messmikrofon** (Kugelcharakteristik, z. B. Elektret-Messmikrofon mit Phantomspeisung).
- Ein **Audio-Interface** mit mindestens zwei Eingängen und einem Ausgang.
- Ein kurzes **Kabel** für die Loopback-Referenz (empfohlen).

## Verkabelung

```
Ausgang 1 ──► Lautsprecher/Mischpult ──► Raum ──► Messmikrofon ──► Eingang 1 (Messung)
    └──────────── Kabel (Loopback) ─────────────────────────────► Eingang 2 (Referenz)
```

Die Referenz ist das Signal, das tatsächlich zum System geht. Die Übertragungsfunktion vergleicht Messung und
Referenz – deshalb spielt es keine Rolle, welches Signal läuft (Rauschen, Musik, Sprache).

## Audio-Einstellungen

- **Windows:** ASIO (falls der Treiber des Interfaces es anbietet) oder WASAPI. MME/DirectSound vermeiden – sie
  haben schwankende Latenzen.
- **macOS:** Core Audio, das Interface direkt auswählen.
- **Abtastrate:** 48 kHz ist ein guter Standard.
- Eingänge für Messung und Referenz sowie den Ausgang des Generators im Dialog **Audio-Einstellungen…** wählen.

## Pegel

- Eingangsverstärkung am Interface so einstellen, dass die Pegelanzeige unten rechts nicht über etwa −6 dBFS geht.
- Den Generator mit niedrigem Pegel starten. Unter **Generator → Einstellungen** lässt sich eine
  **Pegelgrenze** zum Schutz der Lautsprecher festlegen. **M** schaltet sofort stumm.

## Kalibrieren (für SPL)

Für absolute Schallpegel einen Schallkalibrator (94 dB oder 114 dB, 1 kHz) auf das Mikrofon setzen und im Modus
SPL **Kalibrieren…** wählen. Ohne Kalibrierung zeigt AkustikMess Werte in dBFS.
