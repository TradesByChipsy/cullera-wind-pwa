# Cullera Wind & Welle

Wind- und Wellenvorhersage für Cullera (Valencia) — für Wingfoiler und Surfer.
Kombiniert eine hochaufgelöste Prognose mit **echten Messwerten** aus dem Ort.

**Live:** <https://tradesbychipsy.github.io/cullera-wind-pwa/>

Installierbare PWA ohne Build-Schritt: eine `index.html`, dazu Service Worker und
Manifest. Datenquellen: [Open-Meteo](https://open-meteo.com/) (Prognose) und
[AVAMET](https://www.avamet.org/) (Messung).

---

## Was die App zeigt

**Oben: gemessen.** Was zwei Wetterstationen in Cullera gerade tatsächlich melden.

**Darunter: gerechnet.** Fünf Tageskarten mit Windspitze, Böen, Richtung, Welle und
einer Stundenleiste von 8–20 Uhr.

Bewusst getrennt dargestellt — gemessen ist etwas anderes als gerechnet.

Weitere Eigenschaften:

- Relevantes Zeitfenster: Mo–Fr 15–20 Uhr, Sa/So 8–20 Uhr
- Kopfzahl ist die **Spitze** im Fenster, nicht das Mittel
- **Leitmodell statt Mittelung** (siehe unten)
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
scripts/messwerte.py              holt die AVAMET-Messwerte
.github/workflows/messwerte.yml   führt das Skript alle 30 Min aus
data/observations.json            aktuelle Messung (vom Job geschrieben)
data/messreihe.csv                Messung + Prognose, für die Bias-Auswertung
```

---

## Leitmodell statt Durchschnitt

Ursprünglich mittelte die App über viele Modelle. Das war der Fehler: Am 15.08.2026
zeigte sie 6 kn, während am Strand gefoilt wurde.

Die Nachmittagsthermik an der Küste ist kleinräumig. Globalmodelle mit 10–25 km
Gitterweite fassen Land und Meer in einer Zelle zusammen und dämpfen den Wind über
die Landrauigkeit weg. Ein Median über viele Modelle wirft damit genau die Quelle
raus, die als einzige hinsehen kann.

Deshalb führt pro Tag das **feinste Modell, das das Zeitfenster lückenlos abdeckt**:

| Priorität | Modell | Auflösung | Reicht |
|---|---|---|---|
| 1 | Météo-France AROME HD | 1,5 km | ~69 h |
| 2 | Météo-France AROME | 2,5 km | ~69 h |
| 3 | ICON-EU · DWD | 7 km | 5 Tage |
| 4 | UK Met Office | 10 km | 5 Tage |
| 5 | ARPEGE | 11 km | 5 Tage |
| 6 | GFS · NOAA | 13 km | 5 Tage |

In der Praxis: **Tag 1–3 mit 1,5 km, danach 7 km.** Die übrigen Quellen erscheinen
nur als Streuungsangabe — liegen sie weit auseinander, steht „unsicher" an der Zahl.
Welches Modell gerade führt, zeigt das „Leitmodell"-Etikett in der Quellenliste.

Bei den Wellen führt **EWAM** (5 km), das mit 39,15/-0,20 den Küstenpunkt am besten
trifft.

### Warum das Fenster um 20 Uhr endet

Kein Zufall. AROME deckt den dritten Tag exakt bis 20 Uhr ab — bei einem Fenster bis
21 Uhr fiel es dort als „unvollständig" heraus und der Tag wurde von ICON-EU mit
7 km geführt. Sonnenuntergang ist im August ohnehin gegen 20:55, die gestrichene
Stunde kostet also nichts und bringt einen ganzen Tag in 1,5 km.

AROMEs Reichweite verschiebt sich mit jedem Lauf. Reicht sie am dritten Tag einmal
nicht bis 20 Uhr, fällt die App dort automatisch auf ICON-EU zurück — sichtbar am
Leitmodell-Etikett.

### Bewusst nicht dabei

- **ECMWF IFS 0.25°** — rastet auf 39,0/-0,25 ein und misst damit rund 19 km
  südlich von Cullera, konstant zu niedrig.
- **GFS-Wave** — rastet auf 39,25/0,0 ein, etwa 20 km draußen auf See.

Geprüft und für Cullera **nicht verfügbar** (außerhalb des Modellgebiets):
ICON-D2, HARMONIE-AROME von KNMI und DMI, UKMO 2 km. Die API liefert dort
`latitude: nan`.

---

## Messwerte (AVAMET)

Zwei Stationen in Cullera, beide mit Windmessung:

| Station | ID | Takt | Lage |
|---|---|---|---|
| Cullera Faro | `c21m105e06` | ~15 Min | am Leuchtturm, exponiert am Kap |
| Cullera San Antonio | `c21m105e03` | ~5 Min | im Ort, windgeschützter |

Beide liefern nur **Wind**, keine Wellen — es sind Landstationen
(Temperatur, Feuchte, Richtung, Geschwindigkeit, Niederschlag, Druck).
Gemessene Wellendaten gäbe es nur von Puertos del Estado, deren Bojen aber im
Tiefwasser vor Valencia liegen, ~30 km nördlich. Bei 0,1–0,4 m Wellenhöhe vor Ort
wurde darauf bewusst verzichtet.

### Warum der Umweg über GitHub Actions

AVAMET schickt **keine CORS-Header** — die PWA kann die Seite aus dem Browser
heraus nicht abrufen. Deshalb holt ein Actions-Job die Werte und legt sie als
Datei ins Repo; die App liest sie dann von der eigenen Domain.

```
alle 30 Min (05–19 UTC)
   └─ scripts/messwerte.py
        ├─ liest beide AVAMET-Stationsseiten
        ├─ holt den AROME-Wert für dieselbe Stunde
        ├─ schreibt data/observations.json   → die App
        └─ ergänzt data/messreihe.csv        → die Auswertung
```

Fällt eine Station aus, wird sie übersprungen; fallen beide aus, bleibt die alte
`observations.json` stehen. Messwerte älter als 45 Minuten werden in der App
ausgegraut und als „veraltet" markiert.

### Drei Fallstricke, die Zeit gekostet haben

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

### Messreihe und Bias-Auswertung

`data/messreihe.csv` sammelt Messung und AROME-Prognose für dieselbe Stunde
nebeneinander (`zeit,station,gemessen_kn,grad,arome_kn`). Zeilen werden nach
(Zeit, Station) entdoppelt — sonst bekämen stagnante Phasen und Sensorausfälle
doppeltes Gewicht und würden das Ergebnis Richtung Flaute ziehen.

**Beim Auswerten beachten:** Das Anemometer am Faro steht ca. 20 m hoch, die Modelle
liefern 10-m-Wind. Ein gemessener Mehrwert ist nicht automatisch ein Modellfehler.

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
