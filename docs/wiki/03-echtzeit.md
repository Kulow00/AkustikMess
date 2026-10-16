# Echtzeit: Spektrum und Übertragungsfunktion

## Spektrum

Zeigt die Frequenzverteilung des Messsignals – als Schmalband oder in Bändern von 1/1 bis 1/48 Oktave, mit
A-, C- oder Z-Bewertung. **P** hält die Spitzenwerte. Der Titel zeigt die stärkste Frequenz auf ±0,02 Hz genau
mit Note und Cent-Abweichung.

## Übertragungsfunktion

Vergleicht Messung und Referenz und zeigt **Betrag**, **Phase** und **Kohärenz**.

1. Generator einschalten (rosa Rauschen, periodisch).
2. **Laufzeit finden (D)** – gleicht die Laufzeit zwischen Referenz und Mikrofon aus.
3. Die Kurve beruhigt sich durch Mittelung; **R** setzt die Mittelung zurück.

**Kohärenz** zeigt, wie verlässlich die Messung je Frequenz ist (1 = sehr gut). Bereiche mit niedriger Kohärenz
(Störgeräusche, starker Hall) werden ausgeblendet.

**MTW (Multi-Time-Window)** ist der Standard: Mehrere FFT-Längen ergeben im Bass eine feine und im Hochton eine
schnelle Auflösung, etwa 1/24 Oktave über den ganzen Bereich.

## Fadenkreuz und Kammerton

Mit der Maus über ein Diagramm fahren: genaue Frequenz, Note mit Cent-Abweichung und Messwert. Den Bezugston
(A4) stellt **♪ Kammerton** ein – mit Voreinstellungen, Eingabe auf 0,01 Hz genau oder „Ton messen“.

## Kurven speichern und vergleichen

- **S** speichert die Übertragungsfunktion, **⇧S** das Spektrum (mit Namen, z. B. „Reihe 10 links“).
- **Differenz A − B:** zwei gespeicherte Kurven markieren (Strg+Klick).
- **Live relativ:** zeigt live die Änderung gegenüber einer gespeicherten Kurve – ideal beim Einstellen eines EQs.
- **Zielkurve:** Flach, Live-Hauskurve, Sprache, X-Kurve oder eigene Datei (Zeilen „Frequenz dB“, auch .frd) mit
  Toleranzband.
- Export als CSV.

## Crossover ausrichten

Sub allein und Top allein messen und speichern, beide markieren → **Crossover…**. Laufzeit, Polarität und Pegel
verschieben und die Summe sofort sehen. **Optimum finden** sucht die beste Einstellung im markierten
Übergangsbereich.
