# Impulsantwort und Raumakustik

## Messen

1. Modus **Impulsantwort** (Taste 2).
2. **Messen** (Eingabetaste). AkustikMess spielt einen Sinus-Sweep und berechnet daraus die Impulsantwort.
3. Mit Loopback-Referenz wird die Latenz des Interfaces automatisch herausgerechnet. Mehrere Messungen lassen
   sich mitteln.

## Ansichten

Linear, logarithmisch, ETC (Energie-Zeit-Kurve), Schroeder-Abklingkurve, Spektrogramm und Frequenzgang.

## Kennwerte je Oktavband

| Kennwert | Bedeutung |
|---|---|
| EDT | Early Decay Time – wie hallig der Raum klingt |
| T20 / T30 | Nachhallzeit aus 20 bzw. 30 dB Abklingen (nach ISO 3382) |
| C50 | Deutlichkeit für Sprache |
| C80 | Klarheit für Musik |
| D50 | Deutlichkeitsgrad |
| Ts | Schwerpunktzeit |

Die Auswertung kompensiert das Grundrauschen (Lundeby-Verfahren), damit die Nachhallzeit auch bei mäßigem
Störabstand stimmt.

## Sprachverständlichkeit (STI, STIPA)

STI und STIPA werden indirekt aus der Impulsantwort nach IEC 60268-16 berechnet – ohne Hörmaskierung und
Hörschwelle. Für Abnahmemessungen von Sprachalarmanlagen gelten zusätzliche Anforderungen an Messsystem und
Kalibrierung.

## Dateien

Impulsantworten lassen sich als WAV speichern und laden.
