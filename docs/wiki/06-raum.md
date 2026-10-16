# Raum: Lautsprecher planen und Pegel vorhersagen

Der Modus **Raum** (Taste 4) zeigt in der Draufsicht, wie laut und wie gleichmäßig es auf der Hörfläche ist –
je Frequenzband oder breitbandig A-bewertet. Ähnlich wie bei Planungsprogrammen werden alle Lautsprecher mit
Laufzeit, Delay, Polarität und Frequenzweiche **phasenrichtig** addiert. So sieht man Abdeckung, Interferenzen
(z. B. die „Power-Alley“ zwischen zwei Sub-Stacks) und die Wirkung von Sub-Arrays.

## Berechnung ein- und ausschalten

Oben in der Seitenleiste steht der große Schalter **▶ Berechnung starten** (orange). Er ist beim Start **aus**:
Raum, Lautsprecher und Messpunkte lassen sich in Ruhe anlegen und bearbeiten, ohne dass nach jeder Änderung neu
gerechnet wird. Die Lautsprecher-Positionen und die 3D-Geometrie sind trotzdem sofort aktuell; eine alte Karte wird
abgeblendet. Ein Klick schaltet die Berechnung ein (grün) – dann wird nach jeder Änderung automatisch neu
gerechnet, bis man wieder pausiert.

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

## Darstellungen

Oben in der Seitenleiste unter **Darstellung → Ansicht**:

| Ansicht | Zeigt |
|---|---|
| Pegel | Pegelkarte je Band oder A-bewertet; mit **Raumakustik einrechnen** inkl. Reflexionen und Nachhall |
| STI (Sprachverständlichkeit) | Vorhersage nach IEC 60268-16 aus Direktschall, Nachhall und Störgeräusch – Ziel für Sprachalarmanlagen: Mittel ≥ 0,50 |
| Wellenbild – Draufsicht | animierte Wellenausbreitung bei einer Frequenz auf Hörhöhe: wo sich Wellen verstärken (kräftige Farben) und auslöschen (weiß, ohne Bewegung) |
| Wellenbild – Längsschnitt | dasselbe als Schnitt durch den Raum (Tiefe × Höhe) bei wählbarem x |
| Raummode | Druckverteilung einer Raummode: rote Bereiche = Überhöhung, blaue = Loch. Die Liste zeigt alle Moden bis 250 Hz |

Die Karte und der Tab **3D** (drehen mit der linken Maustaste, zoomen mit dem Mausrad) zeigen Raum, Bühne,
Lautsprecher mit Ausrichtung, Messpunkte und alle Hörflächen mit ihrer Pegel- bzw. STI-Karte.

### 3D-Ansicht und Seitenansicht

Im Tab **3D** stehen oben feste Blickwinkel: **Perspektive**, **Seitenansicht**, **Draufsicht**, **Von hinten
(Publikum)** und **Von der Bühne**. Seiten- und Draufsicht sind nahezu verzerrungsfrei (wie eine Planzeichnung).

Mit **Abstrahlung der Tops (−6 dB) zeigen** wird für jeden Top die Achse (weiß) und die −6-dB-Abdeckung
(blaue Kanten, durchscheinender Kegel) bis zur Hörhöhe bzw. bis zur nächsten Wand gezeichnet. In der
**Seitenansicht** sieht man so direkt, wie hoch die Tops strahlen und ab wo bzw. bis wohin z. B. ein Top mit 70°
vertikal das Publikum abdeckt. Unter dem Bild steht für jeden Top: wo die Achse die Hörhöhe trifft und von wo bis
wo der −6-dB-Bereich reicht („darüber“ = die obere Kante strahlt über die Hörfläche hinweg). Der Öffnungswinkel
stammt aus der Tabelle oder – bei importierten Polardaten – aus der gemessenen Abstrahlung bei 2 kHz.

Auch der 2D-**Längsschnitt** zeigt Achse und obere/untere Kante der Tops.

## Raumakustik

- **Reflexionen 1. Ordnung:** Spiegelquellen an Seitenwänden, Rückwand, Wand gegenüber, Boden und Decke.
- **Absorptionsgrade α** für Boden, Wände und Decke: 0 = schallhart (Beton, Glas), ca. 0,3 = Publikum/Teppich,
  ab 0,7 = Akustikdecke oder Absorber.
- **Nachhallzeit:** berechnet nach Sabine aus Raumgröße und α – oder mit **Aus Messung übernehmen** die T30
  (sonst T20) der letzten Messung im Modus Impulsantwort. So passt die Vorhersage zum echten Raum.
- **Störgeräusch** in dB(A) (Lüftung, Publikum) – geht in die STI-Vorhersage ein.

## Weitere Hörflächen

Unter **Weitere Hörflächen → Hinzufügen…** z. B. eine Empore anlegen (Rechteck in der Draufsicht und Ohrhöhe über
dem Hallenboden). In der Karte unter **Hörfläche** auswählen; die 3D-Ansicht zeigt alle Flächen gleichzeitig.

## Gemessene Abstrahlung (Polardaten)

Statt der Öffnungswinkel kann für jeden Lautsprecher eine gemessene Abstrahlung verwendet werden: Lautsprecher
in der Tabelle markieren → **Abstrahlung importieren…** → Datei mit der horizontalen, optional einer zweiten mit
der vertikalen Ebene. Format (CSV/Text, `;` `,` oder Tab, Dezimalkomma erlaubt):

```
Hz;0;10;20;30;…;180
125;0;-0,1;-0,3;…
1000;0;-0,5;-1,8;…
```

Erste Zeile: Winkel ab 0° (Achse), erste Spalte: Frequenz, Werte in dB (werden auf die Achse normiert). Solche
Tabellen exportieren Messprogramme wie ARTA, REW oder VituixCAD. **Öffnungswinkel verwenden** schaltet zurück.
Herstellerdateien im GLL- oder CLF-Binärformat lassen sich nicht direkt öffnen (nicht offen dokumentiert).

## Grenzen

Das Modell rechnet mit Punktquellen im Rechteckraum, Reflexionen 1. Ordnung und einem statistischen
Nachhallfeld. Abdeckung, Interferenzen, Laufzeiteffekte und die Größenordnung von Nachhall und STI stimmen gut;
für komplexe Raumformen, Line-Arrays oder Abnahmen nach Norm ist eine Messung bzw. eine vollständige
Simulationssoftware nötig. Raummoden werden für den leeren Rechteckraum berechnet.
