# Cullera Wind & Welle

Wind- und Wellenvorhersage für Cullera (Valencia) — für Wingfoiler und Surfer.
Kombiniert eine hochaufgelöste Prognose mit **echten Messwerten** aus dem Ort.

**Live:** <https://tradesbychipsy.github.io/cullera-wind-pwa/>

Installierbare PWA ohne Build-Schritt: eine `index.html`, dazu Service Worker und
Manifest. Datenquellen: [Open-Meteo](https://open-meteo.com/) (Prognose) und
[AVAMET](https://www.avamet.org/) (Messung).

---

## Was die App zeigt

**Oben: gemessen.** Was drei Wetterstationen in Cullera gerade tatsächlich melden.

**Darunter: gerechnet.** Fünf Tageskarten mit Windspitze, Böen, Richtung, Welle und
einer Stundenleiste von 8–20 Uhr.

Bewusst getrennt dargestellt — gemessen ist etwas anderes als gerechnet.

Weitere Eigenschaften:

- Relevantes Zeitfenster: Mo–Fr 15–20 Uhr, Sa/So 8–20 Uhr
- Kopfzahl ist die **Spitze** im Fenster, nicht das Mittel
- **Leitmodell statt Mittelung** (siehe unten)
- **Bias-Korrektur aus der eigenen Messreihe** — die Kopfzahl ist am Standort
  nachkalibriert, sobald genug Messpaare vom Marenyet vorliegen
- **Nowcast-Leiste** in 15-Minuten-Schritten für die nächsten Stunden
- **Chance statt nur Zahl** — 40 Ensemble-Läufe sagen, wie sicher der Tag ist
- **AEMET als zweite Meinung** in der Quellenliste, sofern ein Schlüssel hinterlegt ist
- Auflandig/ablandig-Hinweis — Cullera schaut nach Osten: Wind aus O = auflandig
  (drückt an Land), aus W = ablandig ⚠️ (drückt aufs offene Meer)
- App-Shell wird offline gecacht, **Wetterdaten nie** — die kommen immer live

---

## Aufbau

```
index.html                        die komplette App
sw.js                             Service Worker (Offline-Shell, Cache-Strategie)
manifest.webmanifest              Installierbarkeit
icons/                            App-Icons
scripts/messwerte.py              holt Messwerte, Prognosen und AEMET
scripts/test_app.mjs              Tests der Rechenfunktionen aus index.html
scripts/test_messwerte.py         Tests des Abrufskripts
.github/workflows/messwerte.yml   hält das Skript im 15-Minuten-Takt am Laufen
data/observations.json            aktuelle Messung (vom Job geschrieben)
data/messreihe.csv                Messung + AROME, Grundlage der Bias-Korrektur
data/prognosereihe.csv            alle Modelle je Stunde, für die Modellauswertung
data/aemet.json                   AEMET-Vorhersage (nur mit hinterlegtem Schlüssel)
```

---

## Leitmodell statt Durchschnitt

Ursprünglich mittelte die App über viele Modelle. Das war der Fehler: Am 15.08.2026
zeigte sie 6 kn, während am Strand gefoilt wurde.

Die Nachmittagsthermik an der Küste ist kleinräumig. Globalmodelle mit 10–25 km
Gitterweite fassen Land und Meer in einer Zelle zusammen und dämpfen den Wind über
die Landrauigkeit weg. Ein Median über viele Modelle wirft damit genau die Quelle
raus, die als einzige hinsehen kann.

### Der Prognosepunkt

**39,142 / −0,239** — die Position der AVAMET-Station el Marenyet. Bewusst genau
dorthin gelegt, wo gemessen wird: Die Bias-Korrektur eicht den Modellwert gegen
diese Station, und das ist nur sinnvoll, wenn beide denselben Ort meinen.

Vorher lag er auf 39,169 / −0,229, gut 3 km weiter nördlich — bei AROME HD zwei
Gitterzellen. Der Punkt steckt an zwei Stellen und muss in beiden gleich sein:
`LAT/LON` in `index.html` und in `scripts/messwerte.py`.

Deshalb führt pro Tag das **feinste Modell, das das Zeitfenster lückenlos abdeckt**:

| Priorität | Modell | Auflösung | Gitterpunkt | Reicht |
|---|---|---|---|---|
| 1 | Météo-France AROME HD | 1,5 km | 0,2 km | ~69 h |
| 2 | Météo-France AROME | 2,5 km | 1,3 km | ~69 h |
| 3 | ECMWF IFS · HRES | 9 km | 2,4 km | 15 Tage |
| 4 | ICON-EU · DWD | 7 km | 2,1 km | 5 Tage |
| 5 | UK Met Office | 10 km | 6,2 km | 5 Tage |
| 6 | ARPEGE | 11 km | 8,3 km | 4 Tage |
| 7 | GFS · NOAA | 13 km | 5,0 km | 16 Tage |

Spalte „Gitterpunkt" = Abstand des tatsächlich ausgelesenen Punktes zum
Prognosepunkt, gemessen am 10.09.2026. Die API meldet ihn in jeder Antwort zurück.

**Ab Platz 3 entscheidet nicht mehr die Auflösung allein.** ECMWF IFS ist mit 9 km
gröber als ICON-EU mit 7 km, steht aber davor: Es verifiziert ab Tag 2 durchweg
besser, und sein Gitterpunkt liegt mit 2,4 gegen 2,1 km praktisch gleich nah. Das ist die
einzige Ausnahme von der Auflösungsregel — und sie ist eine Annahme, keine Messung.
Sobald die Messreihe genug Tag-3-Paare hat, lässt sie sich nachprüfen.

In der Praxis: **Tag 1–3 mit 1,5 km, danach 9 km.** Die übrigen Quellen erscheinen
nur als Streuungsangabe — liegen sie weit auseinander, steht „unsicher" an der Zahl.
Welches Modell gerade führt, zeigt das „Leitmodell"-Etikett in der Quellenliste.

Bei den Wellen führt **EWAM** (5 km), das mit 39,15/-0,20 den Küstenpunkt am besten
trifft — 3,5 km vom Prognosepunkt. Alle vier Wellenmodelle liefern dort unverändert
Werte; der Seepunkt ist durch die Verschiebung nicht verloren gegangen.

### Warum das Fenster um 20 Uhr endet

Kein Zufall. AROME deckt den dritten Tag exakt bis 20 Uhr ab — bei einem Fenster bis
21 Uhr fiel es dort als „unvollständig" heraus und der Tag wurde von ICON-EU mit
7 km geführt. Sonnenuntergang ist im August ohnehin gegen 20:55, die gestrichene
Stunde kostet also nichts und bringt einen ganzen Tag in 1,5 km.

AROMEs Reichweite verschiebt sich mit jedem Lauf. Reicht sie am dritten Tag einmal
nicht bis 20 Uhr, fällt die App dort automatisch auf ECMWF IFS zurück — sichtbar am
Leitmodell-Etikett.

### Bewusst nicht dabei

- **ECMWF IFS 0.25° und AIFS 0.25°** — rasten beide auf 39,0/-0,25 ein, also
  15,8 km südlich, konstant zu niedrig. Das gilt **nicht** für `ecmwf_ifs`: Seit
  ECMWF am 1.10.2025 den vollen Echtzeitkatalog unter CC-BY 4.0 geöffnet hat, gibt
  es HRES nativ in 9 km — und damit rückt der Gitterpunkt von 15,8 km auf 2,4 km
  heran. Der frühere Ausschluss war korrekt und ist überholt.
- **ECMWF ENS 0.25°** (51 Mitglieder) — sitzt auf demselben zu weit entfernten
  Punkt. Für die Wahrscheinlichkeit führt deshalb **ICON-EU-EPS**: nur 13 km grob,
  aber 40 Mitglieder und der Gitterpunkt 2,1 km entfernt statt 15,8.
- **GFS-Wave** — rastet auf 39,25/0,0 ein, etwa 20 km draußen auf See.

Geprüft und für Cullera **nicht verfügbar** (außerhalb des Modellgebiets):
ICON-D2, HARMONIE-AROME von KNMI und DMI, UKMO 2 km. Die API liefert dort
`latitude: nan`.

---

## Messwerte (AVAMET)

Drei Stationen in Cullera, alle mit Windmessung:

| Station | ID | Takt | Lage |
|---|---|---|---|
| Cullera Marenyet | `c21m105e07` | ~15 Min | **am Spot**, südlich des Kaps, 2 m ü. M. |
| Cullera Faro | `c21m105e06` | ~15 Min | am Leuchtturm, exponiert am Kap |
| Cullera San Antonio | `c21m105e03` | ~5 Min | im Ort, windgeschützter |

Marenyet ist die Referenz — dort wird gefoilt. Faro und San Antonio liegen beide
auf bzw. nördlich des Kaps und sind dafür kein Stellvertreter: Am 10.09.2026 maß
der Faro um 15:30 Uhr 7,0 kn gegen 5,2 kn am Marenyet, um 16:50 Uhr aber nur noch
4,0 gegen 10,0 kn. Das Verhältnis dreht sich, es ist kein Offset.

Alle drei liefern nur **Wind**, keine Wellen — es sind Landstationen
(Temperatur, Feuchte, Richtung, Geschwindigkeit, Niederschlag, Druck).
Gemessene Wellendaten gäbe es nur von Puertos del Estado, deren Bojen aber im
Tiefwasser vor Valencia liegen, ~30 km nördlich. Bei 0,1–0,4 m Wellenhöhe vor Ort
wurde darauf bewusst verzichtet.

### Warum der Umweg über GitHub Actions

AVAMET schickt **keine CORS-Header** — die PWA kann die Seite aus dem Browser
heraus nicht abrufen. Deshalb holt ein Actions-Job die Werte und legt sie als
Datei ins Repo; die App liest sie dann von der eigenen Domain.

```
alle 15 Min (05–19 UTC)
   └─ scripts/messwerte.py
        ├─ liest die drei AVAMET-Stationsseiten
        ├─ holt alle sieben Modelle für dieselbe Stunde
        ├─ holt die AEMET-Vorhersage (nur mit Schlüssel)
        ├─ ergänzt data/prognosereihe.csv    → Modellauswertung
        ├─ schreibt data/aemet.json          → zweite Meinung
        ├─ schreibt data/observations.json   → die App
        └─ ergänzt data/messreihe.csv        → die Auswertung
```

Fällt eine Station aus, wird sie übersprungen; fallen alle aus, bleibt die alte
`observations.json` stehen. Messwerte älter als 45 Minuten werden in der App
ausgegraut und als „veraltet" markiert.

### Warum der Job eine Schleife dreht

Weil GitHub geplante Workflows auf freien Repos nur sporadisch startet. Der Cron
stand auf `0,30 5-19 * * *`, also 30 Läufe am Tag. Tatsächlich kamen an:

```
03.09. 4    04.09. 4    05.09. 5    06.09. 5
07.09. 3    08.09. 4    09.09. 4    10.09. 2
```

Rund ein Achtel. Deshalb sammelte die Messreihe in 25 Tagen 460 Zeilen statt
mehrerer Tausend, und die stationsgenaue Bias-Korrektur hätte Monate gebraucht,
um überhaupt anzuspringen.

Die Lösung verlässt sich nicht mehr darauf, dass ein geplanter Start ankommt:
Jeder Lauf, der tatsächlich startet, bleibt bis zu 5,5 Stunden am Leben und holt
darin alle 15 Minuten neu. Fällt ein Start aus, läuft die Schleife des vorigen
weiter; landet ein neuer, löst er den alten ab (`cancel-in-progress`). Bei
beobachteten Lücken von 4–5 Stunden zwischen zwei tatsächlichen Starts deckt das
den Tag durchgehend ab.

Kosten: keine. Das Repo ist öffentlich, damit sind die Actions-Minuten auf den
Standard-Runnern kostenlos. Auf einem privaten Repo wäre dieser Entwurf falsch —
er würde das Monatskontingent in wenigen Tagen aufbrauchen.

Wer den Takt wirklich auf die Minute genau braucht, müsste von außen anstoßen:
ein freier Cron-Dienst, der die `workflow_dispatch`-Schnittstelle aufruft. Das
kostet ein Token als Repo-Secret und einen Account mehr — dafür kommt jeder Lauf.

---

## Tests

```bash
node scripts/test_app.mjs        # Rechenfunktionen aus index.html
python scripts/test_messwerte.py # Abrufskript
```

Beide laufen ohne Netz, ohne Abhängigkeiten und ohne Build-Schritt — passend zum
Rest des Projekts. Zusammen 76 Prüfungen, Rückgabewert 1 bei Fehlern.

`test_app.mjs` schneidet die Funktionen per Regex aus dem `<script>`-Block von
`index.html` und lädt sie als Modul. Damit wird der **echte** Quelltext geprüft
und nicht eine Kopie, die auseinanderdriften kann. Der Preis: Wer eine dieser
Funktionen umbenennt oder anders formatiert, muss das Suchmuster nachziehen — der
Test sagt dann klar, welches.

Geprüft wird, was ohne Netz und ohne DOM auskommt: die Bias-Bildung, die
Nowcast-Auswahl, die Ensemble-Auswertung, der AEMET-Abgleich, die Richtungs- und
Zeitumrechnung sowie alle Ausfallpfade. Nicht geprüft: Rendering und die echten
API-Antworten — dafür bleibt der Blick in den Browser.

Festgenagelt ist dort auch der teuerste denkbare Fehler des Projekts: dass
spanische und deutsche Himmelsrichtungen verwechselt werden. `AEMET_GRAD["O"]`
muss 270 sein, `compass(90)` muss `"O"` sein — beides steht als Test drin.

---

### Vier Fallstricke, die Zeit gekostet haben

- **AEMET gibt die Windrichtung spanisch an — und zwei Kürzel bedeuten dort das
  Gegenteil.** `O` ist *Oeste*, also West; `SO` ist *Suroeste*, also Südwest. In
  der deutschen Rose der App heißen dieselben Kürzel Ost und Südost. Ungeprüft
  übernommen wäre aus ablandigem Westwind auflandiger Ostwind geworden — aus einer
  Warnung eine Einladung. Das Abrufskript übersetzt deshalb in Grad
  (`AEMET_GRAD`), und die App bildet daraus mit ihrer eigenen Rose die Anzeige.
  Beim ersten echten Abruf war das sofort sichtbar: AEMETs Vormittags-`O` wurde
  zu 270° = W, der Nachmittag zu 90° = O — was zur gemessenen Seebrise passt.

- **AVAMET kodiert die Ortszeit als UTC.** Ein Zeitstempel von 09:00 Ortszeit kommt
  als Epoch für 09:00 UTC an. Wer ihn normal als UTC liest, landet im Sommer zwei
  Stunden in der Zukunft und hält frische Messungen für Vorhersagen.
- **Der Serienname steht hinter den Daten.** Die Stationsseite bettet
  Highcharts-Serien ein als `data:[…],color:…,name:'Velocitat'`. Zwischen beiden
  liegen bei der Richtungsserie über 200 Zeichen Konfiguration.
- **Cache-Buster und Service-Worker-Cache vertragen sich nicht von allein.** Die App
  hängt `?t=…` an, damit ohne aktiven Service Worker nichts Altes aus dem
  HTTP-Cache kommt (Pages setzt `max-age=600`). Im Service Worker muss die Query als
  Cache-Schlüssel abgeschnitten werden — sonst legt jeder Abruf einen neuen Eintrag
  an, der Cache wächst unbegrenzt und der Offline-Rückfall trifft nie den zuletzt
  gespeicherten Stand.

### Messreihe und Bias-Korrektur

`data/messreihe.csv` sammelt Messung und AROME-Prognose für dieselbe Stunde
nebeneinander (`zeit,station,gemessen_kn,grad,arome_kn`). Zeilen werden nach
(Zeit, Station) entdoppelt — sonst bekämen stagnante Phasen und Sensorausfälle
doppeltes Gewicht und würden das Ergebnis Richtung Flaute ziehen.

**Die App liest diese Datei bei jedem Laden und korrigiert die angezeigte Zahl
damit selbst.** Je Tagesstunde wird der Median aus (gemessen − prognostiziert)
gebildet und auf den Modellwert addiert. Median statt Mittel, weil ein einzelner
hängender Sensor ein Mittel über acht Werte spürbar verzieht.

**Die Altdaten zählen dafür nicht mit.** Die 460 Zeilen bis zum 10.09.2026 stammen
von Faro und San Antonio und wurden gegen den alten Prognosepunkt geschrieben —
andere Station, anderer Gitterpunkt. Weil als Referenz nur Marenyet zugelassen ist
und diese Station erst ab dem 10.09. mitläuft, fließt in die Korrektur
ausschließlich ein, was gegen den heutigen Punkt gemessen wurde. Die Altdaten
bleiben als Beleg in der Datei, wirken aber nicht auf die Anzeige.

Was der Altbestand sagt (460 Paare, 16.08.–10.09.2026, alter Prognosepunkt):

| | AROME sagt | gemessen | Abweichung |
|---|---|---|---|
| Faro, 15–20 Uhr | 9,2 kn | 5,8 kn | AROME **+3,4 kn zu hoch** |
| San Antonio, 15–20 Uhr | 9,2 kn | 4,0 kn | AROME **+5,1 kn zu hoch** |

Das dreht die Annahme um, auf der das Leitmodell-Prinzip aufsetzt: Das feinste
Modell dämpft die Thermik nicht weg, es überzeichnet sie. Der Fehler ist
tageszeitabhängig — vormittags nahe null, ab 14 Uhr kippend, abends bis −5 kn.

Regeln, nach denen korrigiert wird:

- **Nur AROME HD.** Gegen dieses eine Modell wurde gemessen; die Abweichung auf
  ECMWF oder ICON-EU anzuwenden wäre geraten. Führt ein anderes Modell, zeigt die
  App den Rohwert.
- **Nur gegen Marenyet,** und **nur Stunde für Stunde.** Eine Tagesstunde wird
  erst korrigiert, wenn sie selbst genug Paare hat (`BIAS_MIN_HOUR`); alle anderen
  bleiben roh. Es gibt bewusst **keinen** tageszeitübergreifenden Rückfallwert —
  siehe unten, warum.
- **Die Spitze wird neu gesucht,** nicht nachträglich verschoben — weil der Bias
  über den Tag wandert, kann die Spitzenstunde eine andere sein als im Rohlauf.
- **Die Böe wandert mit,** um denselben Betrag. Gemessen wurde nur der mittlere
  Wind, deshalb bleibt der Böenaufschlag des Modells unangetastet und nur das
  Grundniveau verschiebt sich. Ohne das stünde „Wind 1 kn, Böen 14 kn" nebeneinander.
- **Gedeckelt auf ±8 kn** gegen Ausreißer, und nie unter 0 kn.
- **Die Quellenliste bleibt roh** — sie zeigt die Streuung der Modelle, nicht die
  korrigierte Zahl.

#### Warum es keinen Rückfallwert gibt

Eine frühere Fassung schaltete ab 30 Paaren *insgesamt* scharf und gab Stunden
ohne eigene Stichprobe den Median über alle Stunden. Die echten Marenyet-Daten
zeigen, warum das falsch ist:

```
12 Uhr  +4,5 kn        20 Uhr  -4,0 kn
19 Uhr  -1,7 kn        21 Uhr  -5,0 kn
                Gesamtmedian: -0,2 kn
```

Der Gesamtmedian liegt zwischen Vormittagsüberschuss und Abendfehler und ist
damit in beiden Tageshälften falsch. Er hätte um 21 Uhr −0,2 statt −5,0 korrigiert
und dabei „korrigiert" ins Kartenfeld geschrieben — eine Eichung vorgetäuscht, die
nicht stattfand. Genau das Mitteln über die Tageszeit, das die Stundenaufteilung
verhindern soll.

Jetzt gilt: Jede Stunde wird nur mit ihrer eigenen Stichprobe korrigiert. Solange
keine Stunde genug Paare hat, gibt es überhaupt keine Korrektur.

**Sichtbar in der App:** Geeichte Stunden sind in der Stundenleiste unterstrichen,
und die Karte nennt den Fortschritt (`3/6 Fensterstunden geeicht`). Die Bias-Zeile
erscheint nur, wenn ausgerechnet die Spitzenstunde geeicht ist — sonst steht keine
Behauptung an der großen Zahl. Im Übergang stehen korrigierte und rohe Stunden
nebeneinander; der Sprung dazwischen ist echt und wird markiert statt geglättet.

**Beim Auswerten beachten:** Das Anemometer am Faro steht ca. 20 m hoch, die Modelle
liefern 10-m-Wind. Ein gemessener Mehrwert ist nicht automatisch ein Modellfehler.
Die bisherige Stichprobe ist außerdem klein und windarm (gemessenes Mittel 4–6 kn) —
über kräftige Tage sagt sie noch wenig. Die Korrektur wird von allein besser, je
länger der Job mitschreibt.

### Prognosereihe — alle Modelle mitschreiben

`data/prognosereihe.csv` hält je Stunde fest, was **jedes** der sieben Modelle
für diese Stunde gesagt hat (`zeit,modell,wind_kn,boe_kn,grad`). Langformat, eine
Zeile pro Modell: So braucht ein achtes Modell nie ein Schema-Update, und alte
Auswertungen bleiben lesbar. Entdoppelt nach (Zeit, Modell) — der Job läuft
viermal je Stunde, die Prognose für diese Stunde ändert sich dabei kaum.

Zusammen mit `messreihe.csv` über die Stunde verknüpft ergibt das die Auswertung,
die die eigentliche Frage beantwortet: **Welches Modell liegt an diesem Spot
tatsächlich am nächsten dran?** Bisher stand dort nur `arome_kn`, und die
Reihenfolge der Modelle war eine begründete Annahme. Mit dieser Datei wird sie
nach ein paar Wochen messbar — dieselbe Funktion, für die PredictWind Geld nimmt,
nur mit der Station am eigenen Strand statt einer beliebigen in der Nähe.

Die Datei wächst um rund 100 Zeilen am Tag. Wenn sie irgendwann stört, gehört sie
jahresweise archiviert statt gelöscht.

---

## Nowcast, Chance, zweite Meinung

### Nowcast — die nächsten Stunden in 15-Minuten-Schritten

Über den Tageskarten steht eine Leiste mit dem, was in den nächsten rund fünf
Stunden passiert. Sie kommt aus dem 15-Minuten-Lauf von AROME, der stündlich neu
gerechnet wird — der einzige Lauf hier, der schnell genug nachzieht, um die Brise
beim Einsetzen zu erwischen. Genau das Fenster zwischen „nachmittags entscheiden"
und „am Strand stehen".

Wie beim Leitmodell führt die feinste Quelle, die Werte liefert:

| Priorität | Modell | Auflösung |
|---|---|---|
| 1 | AROME HD 15-Min | 1,5 km |
| 2 | AROME 15-Min | 2,5 km |

Die HD-Variante lieferte am 10.09.2026 gar nichts — auch über Frankreich nicht,
es lag also nicht an der Abdeckung. Deshalb der Rückfall. Welche Quelle gerade
führt, steht rechts über der Leiste.

### Chance — 40 Läufe statt einer Zahl

**ICON-EU-EPS** rechnet denselben Tag 40-mal mit leicht gestörten
Startbedingungen. Daraus wird der Anteil der Läufe, die die Wing-Schwelle von
14 kn erreichen, plus die Spanne, in der 80 % der Läufe liegen.

Die Schwelle stammt aus dem Dashboard der Vorphase (`WING_MIN = 14`), damit die
App dieselbe Sprache spricht.

**Wichtig beim Lesen:** Die Chance kommt aus einem **anderen Modell** als die
große Zahl. ICON-EU-EPS ist mit 13 km deutlich gröber als AROME mit 1,5 km und
verschmiert die Küstenbrise. Deshalb kann die Spitze über der Schwelle liegen,
während die Chance niedrig ist — beide Zahlen stimmen, sie sehen nur verschieden
genau hin. Die Prozentzahl taugt für „wie sicher ist der Tag", nicht als zweite
Meinung zur Höhe.

### AEMET — die zweite Meinung zur Höhe

Dafür steht AEMET in der Quellenliste, abgesetzt unter den Modellen. Spaniens
eigener HARMONIE-AROME-Lauf mit eigener Datenassimilation und eigener Orografie —
und redaktionell geprüft, kein roher Modelloutput. Stimmen AROME und AEMET
überein, ist die Prognose belastbar; wenn nicht, weiß man wenigstens, dass man es
nicht weiß.

Der Schlüssel gehört nicht in eine statische PWA, deshalb holt der Actions-Job
die Daten und legt sie als `data/aemet.json` ab.

Die Vorhersage reicht rund **48 Stunden** — die zweite Meinung erscheint also nur
auf den ersten beiden Tageskarten. Am dritten Tag liefert AEMET nur noch die
Nachtstunden 00–07, die außerhalb jedes Fensters liegen; dass die Zeile dort
fehlt, ist richtig und kein Ausfall.

Abgefragt wird höchstens **einmal pro Stunde** (`AEMET_SCHONFRIST_MIN`), auch
wenn der Job alle 15 Minuten läuft: AEMET rechnet die Vorhersage nur ein paar Mal
am Tag neu, und die Ratenbegrenzung greift schnell — ein einzelner Testabruf
reichte für HTTP 429. Ist die Datei jünger als die Schonfrist, wird gar nicht
erst angefragt.

**Einrichten:**

1. Schlüssel anfordern unter <https://opendata.aemet.es/centrodedescargas/altaUsuario>
   — kommt per E-Mail, kostenlos.
2. Im Repo unter *Settings → Secrets and variables → Actions → New repository
   secret* als `AEMET_API_KEY` hinterlegen.

Fehlt der Schlüssel, überspringt das Skript den Teil und die App zeigt einfach
keine AEMET-Zeile. Nichts bricht.

### Lizenz der Messdaten

AVAMET steht unter **CC BY-NC-ND 4.0** — Namensnennung, nicht-kommerziell. Die
Quellenangabe steht in der Fußzeile der App. `robots.txt` erlaubt den Zugriff auf
die genutzten Seiten. Für eine Nutzung über den privaten Rahmen hinaus wäre eine
Absprache mit `administrador@avamet.org` angebracht.

---

## Aktualisierung der Quellen

| Quelle | neuer Lauf alle | typischer Verzug |
|---|---|---|
| AVAMET (Messung) | 5–15 Min | — |
| AROME HD / AROME | 3 h | ~4 h |
| ICON-EU | 6 h | ~3,5 h |
| ARPEGE | 6 h | ~3,5 h |
| GFS | 6 h | ~5,5 h |
| UK Met Office | 6 h | ~7 h |
| EWAM / ECMWF WAM | 6 h | ~7,5 h |
| MFWAM | 12 h | ~12 h |

Die App holt beim Öffnen bzw. nach 30 Minuten neu — das zieht aber nur denselben
Modelllauf erneut, solange kein neuer vorliegt.

Der Actions-Job läuft alle 30 Minuten, GitHub verzögert geplante Läufe allerdings
regelmäßig um 10–30 Minuten. Ob ein Lauf automatisch oder von Hand kam, steht in der
Actions-Übersicht: **„Scheduled"** gegenüber **„Manually triggered"**.

---

## Entwicklung

### Lokal testen

```bash
python3 -m http.server 8000
```

Dann <http://localhost:8000> öffnen. Service Worker und Manifest brauchen
`http://`/`https://` — ein direkt geöffnetes `file://`-HTML reicht nicht.

Das Sammelskript einzeln laufen lassen:

```bash
python3 scripts/messwerte.py
```

Es braucht keine Abhängigkeiten, nur die Standardbibliothek.

### Anpassungen

Alles im `<script>`-Block oben in `index.html`:

- **Ort:** `LAT` / `LON`
- **Vorhersagetage:** `FORECAST_DAYS`
- **Sichtbare Stunden:** `STRIP_START` / `STRIP_END`
- **Zeitfenster:** `SESSION_WEEKDAY` / `SESSION_WEEKEND`
- **Modelle:** `WIND_MODELS` / `WAVE_MODELS` — **die Reihenfolge ist die
  Priorität**, der erste Eintrag mit lückenloser Abdeckung führt. Verfügbare
  Modelle stehen in der [Open-Meteo-Dokumentation](https://open-meteo.com/en/docs);
  ob eines Cullera abdeckt, verrät ein Testaufruf.

Die Stationen stehen in `scripts/messwerte.py` unter `STATIONS`.

**Nach Änderungen an `index.html` oder `sw.js` die `VERSION` in `sw.js`
hochzählen** — sonst behalten installierte Geräte den alten Cache.

---

## Historie

Ursprünglich gab es ein separates Python-Skript mit stündlichem Actions-Workflow,
das Push-Notifications per ntfy.sh und Web-Push verschickt hat, dazu eine
Subscription-UI in der App. Das war ein Test und wurde im August 2026 vollständig
entfernt. In der Git-Historie ist es bei Bedarf nachlesbar.
