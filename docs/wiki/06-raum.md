# Raum: Lautsprecher planen und Pegel vorhersagen

Der Modus **Raum** (Taste 4) zeigt in der Draufsicht, wie laut und wie gleichmäßig es auf der Hörfläche ist –
je Frequenzband oder breitbandig A-bewertet. Ähnlich wie bei Planungsprogrammen werden alle Lautsprecher mit
Laufzeit, Delay, Polarität und Frequenzweiche **phasenrichtig** addiert. So sieht man Abdeckung, Interferenzen
(z. B. die „Power-Alley“ zwischen zwei Sub-Stacks) und die Wirkung von Sub-Arrays.

## Raum anlegen

In der Seitenleiste unter **Raum**: Länge (Tiefe ab Bühnenkante), Breite, Höhe, **Hörhöhe** (sitzend ≈ 1,2 m,
stehend ≈ 1,7 m) und **Bühnentiefe**. Die Bühne wird mitberechnet – so sieht man, wie viel Bass auf der Bühne
ankommt.

Koordinaten: **x** von links nach rechts (von der Bühne aus gesehen), **y** von der Bühnenkante (0) in den Raum.

## Lautsprecher

Unter der Karte steht die Lautsprecher-Tabelle. **+ Top** und **+ Sub** fügen Lautsprecher hinzu; in der Karte
lassen sie sich mit der Maus verschieben.

| Spalte | Bedeutung |
|---|---|
| Richtung | 0° = gerade in den Raum, positiv = nach rechts |
| Neigung | negativ = nach unten |
| Pegel @1 m | Breitbandpegel in 1 m auf Achse (Datenblatt: max. SPL bzw. Arbeitspegel) |
| Delay, Polarität | wie am Controller eingestellt („−“ = invertiert) |
| Öffnung H/V | Abstrahlwinkel (−6 dB) laut Datenblatt, z. B. 90° × 40° |
| Hochpass/Tiefpass | Trennfrequenzen (Linkwitz-Riley 24 dB/Okt.) |

## Subwoofer-Setups

Unter **Subwoofer-Setup** ein Muster wählen und **Subs erzeugen** – vorhandene Subs werden ersetzt, Tops bleiben.

| Muster | Wirkung |
|---|---|
| L/R-Stacks | klassisch links/rechts – deutliche Interferenzen (Power-Alley in der Mitte) |
| Mitte (Stack) | ein Stapel in der Mitte – gleichmäßig, aber laut auf der Bühne |
| Linie (Broadside) | Subs nebeneinander – schmale Bündelung nach vorn bei langen Reihen |
| Bogen per Delay (Arc) | Linie, die per Delay wie ein Bogen wirkt – gleichmäßiger in der Breite |
| Endfire | Subs hintereinander, vordere verzögert – bündelt nach vorn, leiser hinten |
| Cardioid (Gradient) | hinterer Sub invertiert und verzögert (Abstand λ/4 der Zielfrequenz) – leise auf der Bühne |

Die erzeugten Delays und Polaritäten stehen in der Tabelle und können direkt so am Controller eingestellt werden.

## Anzeige

- **Frequenz:** Breitband (A) oder ein Oktav-/Terzband. Bass-Setups am besten bei 40–100 Hz beurteilen.
- **Farbbereich:** wie viele dB die Farbskala umfasst (rot = lautester Punkt).
- **Statistik:** Median, Min/Max und der Anteil der Fläche innerhalb ±3 dB – ein Maß für die Gleichmäßigkeit.
  Dazu der Bühnenpegel im Vergleich zum Publikum.
- Mit der Maus über der Karte: Position und Pegel an dieser Stelle.

## Messpunkte: Messung und Vorhersage vergleichen

1. **Punkt setzen** und in die Karte klicken, Namen vergeben (z. B. „Reihe 10 links“).
2. **Messung zuordnen…**: ein gespeichertes Spektrum aus dem Echtzeit-Modus wählen (am besten kalibriert, in
   dB SPL) oder einen Pegel eingeben, z. B. vom SPL-Modus.
3. Liste und Karte zeigen Vorhersage, Messung und Abweichung je Band.
4. **Vorhersage an Messung angleichen** setzt eine Pegelkorrektur, damit die Karte zu den echten Pegeln passt.

## Grenzen

Die Vorhersage rechnet im **Freifeld**: ohne Reflexionen, Raummoden und Nachhall. Sie zeigt Abdeckung,
Interferenzen und Laufzeiteffekte zuverlässig; in halligen Räumen sind die tatsächlichen Pegel weiter hinten höher
und die Interferenzen schwächer. Lautsprecher werden als Punktquellen mit vereinfachter Abstrahlung berechnet
(keine Line-Arrays).
