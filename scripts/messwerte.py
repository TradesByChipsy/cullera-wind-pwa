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
    "&wind_speed_unit=kn&forecast_days=1&timezone=Europe%2FMadrid"
)

# AEMET als unabhängige zweite Meinung: Spaniens eigener HARMONIE-AROME-Lauf mit
# eigener Datenassimilation und eigener Orografie. Der Schlüssel gehört nicht in
# den Browser, deshalb holt ihn dieser Job und legt das Ergebnis als Datei ab.
# Ohne Schlüssel wird der Teil übersprungen — die App kommt ohne ihn aus.
AEMET_MUNICIPIO = "46105"  # Cullera
AEMET_URL = (
    "https://opendata.aemet.es/opendata/api/prediccion/especifica"
    f"/municipio/horaria/{AEMET_MUNICIPIO}"
)

# AEMET gibt die Richtung SPANISCH an, und zwei Kürzel bedeuten dort das
# GEGENTEIL des deutschen Kürzels:
#     O  = Oeste     = West     (deutsch O = Ost)
#     SO = Suroeste  = Südwest  (deutsch SO = Südost)
# Ungeprüft übernommen würde aus ablandigem Westwind auflandiger Ostwind – und
# damit aus einer Warnung eine Einladung. Deshalb wird hier in Grad übersetzt;
# die App bildet daraus mit ihrer eigenen Rose die Anzeige.
AEMET_GRAD = {
    "N": 0, "NNE": 22.5, "NE": 45, "ENE": 67.5,
    "E": 90, "ESE": 112.5, "SE": 135, "SSE": 157.5,
    "S": 180, "SSO": 202.5, "SO": 225, "OSO": 247.5,
    "O": 270, "ONO": 292.5, "NO": 315, "NNO": 337.5,
}

# Die Vorhersage wird nur ein paar Mal am Tag neu gerechnet (Feld "elaborado"),
# der Job läuft aber alle 15 Minuten. Häufiger abzufragen bringt nichts und
# läuft in AEMETs Ratenbegrenzung – ein Abruf im Test genügte für HTTP 429.
AEMET_SCHONFRIST_MIN = 60

# Ab hier gilt der Messwert als veraltet – dieselbe Schwelle, die AVAMET auf der
# eigenen Seite verwendet.
STALE_MINUTES = 45

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OBS_PATH = os.path.join(ROOT, "data", "observations.json")
CSV_PATH = os.path.join(ROOT, "data", "messreihe.csv")
PROG_PATH = os.path.join(ROOT, "data", "prognosereihe.csv")
AEMET_PATH = os.path.join(ROOT, "data", "aemet.json")

KMH_TO_KN = 1.852


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "cullera-wind-pwa/1.0"})
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


def prognosen_now():
    """Was sagt jedes Modell für die laufende Stunde? Nur für den Abgleich in den
    CSVs, nicht für die Anzeige — die App holt ihre Werte selbst.

    Gibt (stunde, {modell: {"kn":…, "boe":…, "grad":…}}) zurück. Bei mehreren
    Modellen suffixt Open-Meteo die Keys: wind_speed_10m_icon_eu."""
    stunde = datetime.now(TZ).strftime("%Y-%m-%dT%H:00")
    try:
        d = json.loads(fetch(PROGNOSE_URL))["hourly"]
        i = d["time"].index(stunde)
    except Exception as e:
        print(f"  Prognose-Abgleich übersprungen ({e})")
        return stunde, {}

    out = {}
    for m in WIND_MODELS:
        werte = {}
        for feld, name in (("wind_speed_10m", "kn"),
                           ("wind_gusts_10m", "boe"),
                           ("wind_direction_10m", "grad")):
            reihe = d.get(f"{feld}_{m}")
            werte[name] = reihe[i] if reihe and i < len(reihe) else None
        # Ein Modell ohne Windwert für diese Stunde ist noch nicht gelaufen oder
        # deckt den Zeitpunkt nicht ab – dann gar nichts schreiben.
        if werte["kn"] is not None:
            out[m] = werte
    print(f"  Prognosen für {stunde[11:16]}: " +
          ", ".join(f"{KURZNAME.get(m, m)} {v['kn']:.1f}" for m, v in out.items()))
    return stunde, out


def aemet_prognose():
    """AEMET-Stundenvorhersage für Cullera. Zweistufig: Der erste Aufruf liefert
    nur eine URL, unter der die eigentlichen Daten liegen.

    Ohne Schlüssel (Repo-Secret AEMET_API_KEY) wird der Teil übersprungen; die
    App zeigt dann einfach keine zweite Meinung an."""
    key = os.environ.get("AEMET_API_KEY", "").strip()
    if not key:
        print("  AEMET: kein Schlüssel gesetzt, übersprungen")
        return None
    try:
        meta = json.loads(fetch(f"{AEMET_URL}?api_key={key}"))
        if meta.get("estado") != 200 or not meta.get("datos"):
            print(f"  AEMET: {meta.get('descripcion', 'unerwartete Antwort')}")
            return None
        roh = json.loads(fetch(meta["datos"]).decode("utf-8", errors="replace"))
    except Exception as e:
        print(f"  AEMET übersprungen ({e})")
        return None

    # Struktur: [ { "prediccion": { "dia": [ { "fecha": …,
    #   "vientoAndRachaMax": [ {"direccion":["E"],"velocidad":["10"],"periodo":"08"},
    #                          {"value":"25","periodo":"08"} ] } ] } } ]
    # Einträge mit direccion/velocidad sind der Wind, die mit value die Böe.
    stunden = []
    try:
        for tag in roh[0]["prediccion"]["dia"]:
            datum = str(tag.get("fecha", ""))[:10]
            wind, boeen = {}, {}
            for e in tag.get("vientoAndRachaMax", []):
                p = str(e.get("periodo", "")).zfill(2)[:2]
                if e.get("velocidad"):
                    wind[p] = {
                        "kmh": _erste_zahl(e["velocidad"]),
                        "richtung": (e.get("direccion") or [None])[0],
                    }
                elif e.get("value") not in (None, ""):
                    boeen[p] = _erste_zahl([e["value"]])
            for p in sorted(wind):
                w = wind[p]
                if w["kmh"] is None:
                    continue
                # "C" steht für calma – dann gibt es keine Richtung, nur Windstille.
                grad = AEMET_GRAD.get((w["richtung"] or "").strip().upper())
                stunden.append({
                    "zeit": f"{datum}T{p}:00",
                    "kn": round(w["kmh"] / KMH_TO_KN, 1),
                    "grad": grad,
                    "boe_kn": (round(boeen[p] / KMH_TO_KN, 1)
                               if boeen.get(p) is not None else None),
                })
    except Exception as e:
        print(f"  AEMET: Antwort nicht wie erwartet aufgebaut ({e})")
        return None

    if not stunden:
        print("  AEMET: keine Windstunden in der Antwort")
        return None
    print(f"  AEMET: {len(stunden)} Stunden, ab {stunden[0]['zeit'][11:16]}")
    return {
        "stand": datetime.now(TZ).isoformat(timespec="minutes"),
        "quelle": "AEMET OpenData · HARMONIE-AROME 2,5 km, redaktionell geprüft",
        "gemeinde": "Cullera",
        "stunden": stunden,
    }


def _erste_zahl(werte):
    """AEMET verpackt Zahlen als Liste von Strings, gelegentlich leer."""
    for v in werte or []:
        try:
            return float(str(v).strip())
        except (TypeError, ValueError):
            continue
    return None


def main():
    print("AVAMET-Stationen abrufen:")
    stations = [s for s in (read_station(sid, nm) for sid, nm in STATIONS) if s]

    os.makedirs(os.path.dirname(OBS_PATH), exist_ok=True)

    # Prognosereihe und AEMET ZUERST und unabhängig von den Stationen: Beide
    # hängen nicht an AVAMET. Standen sie hinter dem Ausstieg unten, verlor ein
    # AVAMET-Ausfall – bei Amateurstationen der Normalfall – auch die
    # Modellauswertung und die zweite Meinung für dieselbe Stunde.
    stunde, prognosen = prognosen_now()
    schreibe_prognosereihe(stunde, prognosen)
    schreibe_aemet()

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
        return 0

    arome = prognosen.get(LEITMODELL, {}).get("kn")
    with open(CSV_PATH, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if not bekannt:
            w.writerow(["zeit", "station", "gemessen_kn", "grad", "arome_kn"])
        for s in neu:
            w.writerow([s["gemessen"], s["name"], s["kn_genau"], s["grad"],
                        "" if arome is None else round(arome, 1)])
    print(f"Messreihe: {len(neu)} neue Zeile(n)")
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


def aemet_ist_frisch():
    """Liegt schon eine junge Datei vor? Dann gar nicht erst abfragen."""
    try:
        with open(AEMET_PATH, encoding="utf-8") as f:
            stand = datetime.fromisoformat(json.load(f)["stand"])
    except Exception:
        return False
    alter = (datetime.now(TZ) - stand).total_seconds() / 60
    if alter < AEMET_SCHONFRIST_MIN:
        print(f"  AEMET: Datei ist {alter:.0f} Min alt, Abruf gespart")
        return True
    return False


def schreibe_aemet():
    """Nur schreiben, wenn wirklich Daten kamen – sonst bliebe die App ohne
    zweite Meinung stehen, obwohl gestern noch eine da war."""
    if aemet_ist_frisch():
        return
    daten = aemet_prognose()
    if daten is None:
        return
    with open(AEMET_PATH, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"geschrieben: {AEMET_PATH}")


if __name__ == "__main__":
    sys.exit(main())
