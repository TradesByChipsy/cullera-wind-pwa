#!/usr/bin/env python3
"""
Holt die aktuellen Windmesswerte der drei AVAMET-Stationen in Cullera und legt
sie als data/observations.json ab, damit die PWA sie von der eigenen Domain lesen
kann. AVAMET selbst schickt keine CORS-Header – ein direkter Abruf aus dem Browser
ist deshalb nicht möglich.

Zusätzlich wird jede Messung zusammen mit dem, was AROME für dieselbe Stunde
vorhergesagt hat, an data/messreihe.csv angehängt. Die App liest diese Datei und
korrigiert damit die angezeigte Prognose – siehe Bias-Korrektur in index.html.

Datenquelle: AVAMET (Associació Valenciana de Meteorologia), CC BY-NC-ND 4.0.
"""

import csv
import json
import os
import re
import statistics
import sys
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
# Muss mit LAT/LON in index.html übereinstimmen – sonst vergleicht die Messreihe
# den AROME-Wert eines anderen Gitterpunkts mit der Messung, und die daraus
# gerechnete Bias-Korrektur wäre für die Anzeige wertlos.
# Punkt = AVAMET-Station el Marenyet, 39°08'31" N / 00°14'20" W.
LAT, LON = 39.142, -0.239

# Marenyet steht zuerst: Das ist der Strand, um den es geht, und damit die
# Referenz für die Bias-Korrektur. Faro und San Antonio liegen beide AUF bzw.
# NÖRDLICH des Kaps – bei nördlichen und östlichen Lagen ist das eine andere
# Windwelt als südlich davon. Momentaufnahme 10.09.2026, 15:30 Uhr:
# Faro 7,0 kn, Marenyet 5,2 kn, San Antonio 3,5 kn.
STATIONS = [
    ("c21m105e07", "Cullera Marenyet"),
    ("c21m105e06", "Cullera Faro"),
    ("c21m105e03", "Cullera San Antonio"),
]

AVAMET_URL = "https://www.avamet.org/mxo_i.php?id={}"

# Muss der Reihenfolge von WIND_MODELS in index.html entsprechen. Alle Modelle
# werden mitgeschrieben, nicht nur AROME: Erst damit lässt sich nach ein paar
# Wochen bestimmen, welches Modell an DIESEM Spot wirklich führen sollte —
# dieselbe Auswertung, für die PredictWind Geld nimmt.
WIND_MODELS = [
    "meteofrance_arome_france_hd",
    "meteofrance_arome_france",
    "ecmwf_ifs",
    "icon_eu",
    "ukmo_global_deterministic_10km",
    "meteofrance_arpege_europe",
    "gfs_seamless",
]
LEITMODELL = WIND_MODELS[0]

# Nur für lesbare Log-Zeilen – drei Modelle heißen sonst alle "meteofrance".
KURZNAME = {
    "meteofrance_arome_france_hd": "AROME-HD",
    "meteofrance_arome_france": "AROME",
    "ecmwf_ifs": "ECMWF",
    "icon_eu": "ICON-EU",
    "ukmo_global_deterministic_10km": "UKMO",
    "meteofrance_arpege_europe": "ARPEGE",
    "gfs_seamless": "GFS",
}

PROGNOSE_URL = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={LAT}&longitude={LON}"
    "&hourly=wind_speed_10m,wind_gusts_10m,wind_direction_10m"
    f"&models={','.join(WIND_MODELS)}"
    # past_days=1: Eine Messung kurz nach Mitternacht gehört zur Stunde von
    # gestern 23 Uhr – die muss in der Antwort noch enthalten sein.
    "&wind_speed_unit=kn&past_days=1&forecast_days=1&timezone=Europe%2FMadrid"
)

# Ab hier gilt der Messwert als veraltet – dieselbe Schwelle, die AVAMET auf der
# eigenen Seite verwendet.
STALE_MINUTES = 45

# Bias-Korrektur: Referenz ist NUR Marenyet – dort wird gefoilt, dorthin muss die
# Zahl passen. Faro und San Antonio liegen auf bzw. nördlich des Kaps und
# verhalten sich nicht proportional dazu.
#
# Gerechnet wird hier und nicht in der App: Früher lud die App bei jedem Öffnen
# die komplette messreihe.csv, um daraus den Bias zu bilden. Die Datei wächst um
# rund 7 KB am Tag – nach einem Jahr wären das über 2 MB bei jedem App-Start, auf
# dem Handy, wovon die App nur ein Drittel überhaupt braucht. Jetzt legt der Job
# das fertige Ergebnis als data/bias.json ab, gut ein Kilobyte.
BIAS_STATION = "Cullera Marenyet"
BIAS_MIN_STUNDE = 8   # weniger Paare in einer Stunde = zu zufällig
BIAS_CAP = 8.0        # kn – Deckel gegen hängende Sensoren und Ausreißer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OBS_PATH = os.path.join(ROOT, "data", "observations.json")
CSV_PATH = os.path.join(ROOT, "data", "messreihe.csv")
PROG_PATH = os.path.join(ROOT, "data", "prognosereihe.csv")
BIAS_PATH = os.path.join(ROOT, "data", "bias.json")

KMH_TO_KN = 1.852


def fetch(url, timeout=30, headers=None):
    kopf = {"User-Agent": "cullera-wind-pwa/1.0"}
    kopf.update(headers or {})
    req = urllib.request.Request(url, headers=kopf)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def extract_series(html, name_prefix):
    """
    Die Stationsseite bettet Highcharts-Serien ein. Der Serienname steht dabei
    HINTER den Daten, nicht davor:
        data:[[epoch_ms,wert],…],color:'#…',…,name:'Velocitat'
    Zwischen data und name liegen bei der Richtungsserie über 200 Zeichen
    Marker-Konfiguration – das Suchfenster muss entsprechend großzügig sein.
    Gibt {epoch_ms: wert} zurück.
    """
    for m in re.finditer(r"data:\s*\[(\[\d{10,13},[^\]]*\](?:,\[\d{10,13},[^\]]*\])*)\]", html):
        tail = html[m.end():m.end() + 500]
        nm = re.search(r"name:\s*'([^']*)'", tail)
        if not nm or not nm.group(1).startswith(name_prefix):
            continue
        return {
            int(ts): float(val)
            for ts, val in re.findall(r"\[(\d{10,13}),\s*([-\d.]+)\]", m.group(1))
        }
    return {}


def avamet_time(ts_ms):
    """
    AVAMET kodiert die ORTSZEIT in den Epoch-Wert, als wäre sie UTC – ein
    Zeitstempel von 09:00 Ortszeit kommt als Epoch für 09:00 UTC an. Wer ihn
    normal als UTC liest, landet im Sommer zwei Stunden in der Zukunft und hält
    frische Messungen für Vorhersagen.
    Also: als naive Ortszeit lesen und die Zone anheften, nicht umrechnen.
    """
    naive = datetime.fromtimestamp(ts_ms / 1000, timezone.utc).replace(tzinfo=None)
    return naive.replace(tzinfo=TZ)


def compass(deg):
    if deg is None:
        return None
    names = ["N", "NNO", "NO", "ONO", "O", "OSO", "SO", "SSO",
             "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return names[round((deg % 360) / 22.5) % 16]


def read_station(sid, name):
    """Jüngsten Messpunkt einer Station holen. Gibt None zurück, wenn die Station
    nicht erreichbar ist oder keine Winddaten liefert – ein Ausfall darf nie den
    ganzen Lauf mitreißen, Amateurstationen fallen gelegentlich aus."""
    try:
        raw = fetch(AVAMET_URL.format(sid))
    except Exception as e:
        print(f"  {name}: nicht erreichbar ({e})")
        return None

    html = raw.decode("utf-8", errors="replace")
    speed = extract_series(html, "Velocitat")
    if not speed:
        print(f"  {name}: keine Windserie gefunden")
        return None
    direction = extract_series(html, "Direcci")

    ts = max(speed)
    measured = avamet_time(ts)
    age_min = (datetime.now(TZ) - measured).total_seconds() / 60
    deg = direction.get(ts)

    print(f"  {name}: {speed[ts]:.1f} km/h = {speed[ts] / KMH_TO_KN:.0f} kn "
          f"aus {compass(deg) or '?'}, {age_min:.0f} Min alt")

    return {
        "name": name,
        "kn": round(speed[ts] / KMH_TO_KN),
        # Ungerundet für die Messreihe: Die Bias-Korrektur soll auf 1 kn genau
        # sein, da darf die Grundlage nicht vorher ±0,5 kn verlieren. Die Anzeige
        # nimmt weiter den ganzzahligen Wert.
        "kn_genau": round(speed[ts] / KMH_TO_KN, 1),
        "grad": round(deg) if deg is not None else None,
        "richtung": compass(deg),
        "gemessen": measured.isoformat(timespec="minutes"),
        "veraltet": age_min > STALE_MINUTES,
    }


def hole_prognosen():
    """Stundenreihen aller Modelle holen – einmal je Lauf, für zwei Zwecke: die
    Prognosereihe (laufende Stunde) und die Paarung in der Messreihe (Stunde der
    Messung). None, wenn Open-Meteo nicht antwortet."""
    try:
        return json.loads(fetch(PROGNOSE_URL))["hourly"]
    except Exception as e:
        print(f"  Prognose-Abgleich übersprungen ({e})")
        return None


def stunde_von(zeitstempel):
    """Aus "2026-09-15T13:54+02:00" wird "2026-09-15T13:00". Die Messzeit von
    AVAMET trägt die Ortszeit, die Stundenreihe von Open-Meteo ebenfalls
    (timezone=Europe/Madrid) – die ersten 13 Zeichen passen also direkt."""
    return f"{zeitstempel[:13]}:00"


def prognosen_fuer(hourly, stunde):
    """Was sagt jedes Modell für eine bestimmte Stunde ("YYYY-MM-DDTHH:00")?

    Gibt {modell: {"kn":…, "boe":…, "grad":…}} zurück, leer, wenn die Stunde
    nicht in der Antwort steckt. Bei mehreren Modellen suffixt Open-Meteo die
    Keys: wind_speed_10m_icon_eu."""
    if not hourly:
        return {}
    try:
        i = hourly["time"].index(stunde)
    except (KeyError, ValueError):
        return {}

    out = {}
    for m in WIND_MODELS:
        werte = {}
        for feld, name in (("wind_speed_10m", "kn"),
                           ("wind_gusts_10m", "boe"),
                           ("wind_direction_10m", "grad")):
            reihe = hourly.get(f"{feld}_{m}")
            werte[name] = reihe[i] if reihe and i < len(reihe) else None
        # Ein Modell ohne Windwert für diese Stunde ist noch nicht gelaufen oder
        # deckt den Zeitpunkt nicht ab – dann gar nichts schreiben.
        if werte["kn"] is not None:
            out[m] = werte
    return out


def main():
    print("AVAMET-Stationen abrufen:")
    stations = [s for s in (read_station(sid, nm) for sid, nm in STATIONS) if s]

    os.makedirs(os.path.dirname(OBS_PATH), exist_ok=True)

    # Die Prognosereihe ZUERST und unabhängig von den Stationen: Sie hängt nicht
    # an AVAMET. Stünde sie hinter dem Ausstieg unten, verlöre ein AVAMET-Ausfall
    # – bei Amateurstationen der Normalfall – auch die Modellauswertung für
    # dieselbe Stunde.
    roh_prognosen = hole_prognosen()
    stunde = datetime.now(TZ).strftime("%Y-%m-%dT%H:00")
    prognosen = prognosen_fuer(roh_prognosen, stunde)
    if prognosen:
        print(f"  Prognosen für {stunde[11:16]}: " +
              ", ".join(f"{KURZNAME.get(m, m)} {v['kn']:.1f}" for m, v in prognosen.items()))
    schreibe_prognosereihe(stunde, prognosen)

    if not stations:
        print("Keine Station lieferte Daten – observations.json bleibt unverändert.")
        return 1

    # kn_genau bleibt draußen: Die App zeigt ganze Knoten, die Nachkommastelle
    # wird nur in der Messreihe gebraucht. Was die App nicht liest, gehört auch
    # nicht in ihre Datei.
    payload = {
        "stand": datetime.now(TZ).isoformat(timespec="minutes"),
        "quelle": "AVAMET (CC BY-NC-ND 4.0)",
        "stationen": [{k: v for k, v in s.items() if k != "kn_genau"}
                      for s in stations],
    }
    with open(OBS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"geschrieben: {OBS_PATH}")

    # Messreihe fortschreiben – Grundlage für die spätere Bias-Auswertung.
    # Der Job läuft alle 30 Min, die Stationen liefern alle 5–15 Min. Hat eine
    # Station seit dem letzten Lauf nichts Neues geschickt (Ausfall, Sensor hängt),
    # käme dieselbe Messung ein zweites Mal in die Datei und stagnante Phasen
    # bekämen im Mittel doppeltes Gewicht. Deshalb nach (Zeit, Station) entdoppeln.
    bekannt = set()
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, encoding="utf-8", newline="") as f:
            for row in csv.reader(f):
                if len(row) >= 2:
                    bekannt.add((row[0], row[1]))

    neu = [s for s in stations
           if not s["veraltet"] and (s["gemessen"], s["name"]) not in bekannt]

    if not neu:
        print("Keine neue Messung seit dem letzten Lauf – Messreihe unverändert.")
        schreibe_bias()
        return 0

    with open(CSV_PATH, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if not bekannt:
            w.writerow(["zeit", "station", "gemessen_kn", "grad", "arome_kn"])
        for s in neu:
            # Die Prognose der Stunde, in der GEMESSEN wurde – nicht der, in der
            # der Job läuft. Vorher bekam eine Messung von 11:59, die der Job um
            # 12:02 abholte, den 12-Uhr-Wert, landete in der Bias-Rechnung aber
            # unter 11 Uhr. Am 15.09.2026 betraf das 28 von 203 Paaren (14 %),
            # gehäuft dort, wo der Wind schnell steigt oder fällt.
            arome = (prognosen_fuer(roh_prognosen, stunde_von(s["gemessen"]))
                     .get(LEITMODELL, {}).get("kn"))
            w.writerow([s["gemessen"], s["name"], s["kn_genau"], s["grad"],
                        "" if arome is None else round(arome, 1)])
    print(f"Messreihe: {len(neu)} neue Zeile(n)")

    # Erst jetzt, mit den frischen Zeilen drin.
    schreibe_bias()
    return 0


def schreibe_prognosereihe(stunde, prognosen):
    """Langformat: eine Zeile je Stunde und Modell. Damit braucht eine neue
    Modellspalte nie ein Schema-Update, und die Datei bleibt mit jedem Auswerten
    kompatibel. Entdoppelt nach (Zeit, Modell) – der Job läuft viermal je Stunde,
    die Prognose für diese Stunde ändert sich dabei kaum."""
    if not prognosen:
        return
    bekannt = set()
    if os.path.exists(PROG_PATH):
        with open(PROG_PATH, encoding="utf-8", newline="") as f:
            for row in csv.reader(f):
                if len(row) >= 2:
                    bekannt.add((row[0], row[1]))

    neu = [(m, v) for m, v in prognosen.items() if (stunde, m) not in bekannt]
    if not neu:
        return
    with open(PROG_PATH, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if not bekannt:
            w.writerow(["zeit", "modell", "wind_kn", "boe_kn", "grad"])
        for m, v in neu:
            w.writerow([stunde, m,
                        round(v["kn"], 1),
                        "" if v["boe"] is None else round(v["boe"], 1),
                        "" if v["grad"] is None else round(v["grad"])])
    print(f"Prognosereihe: {len(neu)} neue Zeile(n)")


def rechne_bias(zeilen):
    """Aus den Messpaaren je Tagesstunde bestimmen, wie weit AROME danebenliegt.

    `zeilen` sind Dicts aus messreihe.csv. Zurück kommt {stunde: {"kn":…,"n":…}},
    und zwar NUR für Stunden mit genug eigenen Paaren. Es gibt bewusst keinen
    tageszeitübergreifenden Rückfallwert: Die echten Marenyet-Daten liegen
    vormittags bei +4,5 kn und abends bei −5,0 kn, der Median über alles bei
    −0,2 kn. Der wäre in beiden Tageshälften falsch und würde eine Eichung
    vortäuschen, die nicht stattgefunden hat.

    Median statt Mittel, weil ein einzelner hängender Sensor ein Mittel über acht
    Werte spürbar verzieht."""
    nach_stunde = {}
    for r in zeilen:
        if r.get("station") != BIAS_STATION:
            continue
        try:
            diff = float(r["gemessen_kn"]) - float(r["arome_kn"])
            stunde = int(r["zeit"][11:13])
        except (KeyError, ValueError, TypeError):
            continue
        nach_stunde.setdefault(stunde, []).append(diff)

    raus = {}
    for stunde, diffs in sorted(nach_stunde.items()):
        if len(diffs) < BIAS_MIN_STUNDE:
            continue
        kn = max(-BIAS_CAP, min(BIAS_CAP, statistics.median(diffs)))
        raus[str(stunde)] = {"kn": round(kn, 1), "n": len(diffs)}
    return raus


def schreibe_bias():
    """data/bias.json schreiben – das ist die Datei, die die App liest."""
    if not os.path.exists(CSV_PATH):
        return
    with open(CSV_PATH, encoding="utf-8", newline="") as f:
        stunden = rechne_bias(list(csv.DictReader(f)))

    # Bewusst OHNE Zeitstempel: Der Job läuft alle 15 Minuten, ein "stand"-Feld
    # würde sich jedes Mal ändern und damit alle 15 Minuten einen Commit
    # auslösen, auch wenn sich an den Zahlen nichts getan hat.
    payload = {
        "station": BIAS_STATION,
        "modell": LEITMODELL,
        "min_pro_stunde": BIAS_MIN_STUNDE,
        "stunden": stunden,
    }
    with open(BIAS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.write("\n")
    if stunden:
        print("  Bias: " + ", ".join(
            f"{h}h {v['kn']:+.1f} (n={v['n']})" for h, v in stunden.items()))
    else:
        print(f"  Bias: noch keine Stunde mit {BIAS_MIN_STUNDE} Paaren")


if __name__ == "__main__":
    sys.exit(main())
