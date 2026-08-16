#!/usr/bin/env python3
"""
Holt die aktuellen Windmesswerte der beiden AVAMET-Stationen in Cullera und legt
sie als data/observations.json ab, damit die PWA sie von der eigenen Domain lesen
kann. AVAMET selbst schickt keine CORS-Header – ein direkter Abruf aus dem Browser
ist deshalb nicht möglich.

Zusätzlich wird jede Messung zusammen mit dem, was AROME für dieselbe Stunde
vorhergesagt hat, an data/messreihe.csv angehängt. Daraus lässt sich nach ein paar
Wochen bestimmen, ob AROME für Cullera systematisch daneben liegt.

Datenquelle: AVAMET (Associació Valenciana de Meteorologia), CC BY-NC-ND 4.0.
"""

import csv
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
LAT, LON = 39.169, -0.229

STATIONS = [
    ("c21m105e06", "Cullera Faro"),
    ("c21m105e03", "Cullera San Antonio"),
]

AVAMET_URL = "https://www.avamet.org/mxo_i.php?id={}"
AROME_URL = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={LAT}&longitude={LON}"
    "&hourly=wind_speed_10m"
    "&models=meteofrance_arome_france_hd"
    "&wind_speed_unit=kn&forecast_days=1&timezone=Europe%2FMadrid"
)

# Ab hier gilt der Messwert als veraltet – dieselbe Schwelle, die AVAMET auf der
# eigenen Seite verwendet.
STALE_MINUTES = 45

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OBS_PATH = os.path.join(ROOT, "data", "observations.json")
CSV_PATH = os.path.join(ROOT, "data", "messreihe.csv")

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
        "grad": round(deg) if deg is not None else None,
        "richtung": compass(deg),
        "gemessen": measured.isoformat(timespec="minutes"),
        "veraltet": age_min > STALE_MINUTES,
    }


def arome_now():
    """Was sagt AROME für die laufende Stunde? Nur für den Abgleich in der CSV,
    nicht für die Anzeige."""
    try:
        d = json.loads(fetch(AROME_URL))["hourly"]
        key = datetime.now(TZ).strftime("%Y-%m-%dT%H:00")
        return d["wind_speed_10m"][d["time"].index(key)]
    except Exception as e:
        print(f"  AROME-Abgleich übersprungen ({e})")
        return None


def main():
    print("AVAMET-Stationen abrufen:")
    stations = [s for s in (read_station(sid, nm) for sid, nm in STATIONS) if s]

    if not stations:
        print("Keine Station lieferte Daten – observations.json bleibt unverändert.")
        return 1

    os.makedirs(os.path.dirname(OBS_PATH), exist_ok=True)

    payload = {
        "stand": datetime.now(TZ).isoformat(timespec="minutes"),
        "quelle": "AVAMET (CC BY-NC-ND 4.0)",
        "stationen": stations,
    }
    with open(OBS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.write("\n")

    # Messreihe fortschreiben – Grundlage für die spätere Bias-Auswertung
    arome = arome_now()
    new = not os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["zeit", "station", "gemessen_kn", "grad", "arome_kn"])
        for s in stations:
            if s["veraltet"]:
                continue  # veraltete Messung nicht in die Auswertung schleppen
            w.writerow([s["gemessen"], s["name"], s["kn"], s["grad"],
                        "" if arome is None else round(arome, 1)])

    print(f"\ngeschrieben: {OBS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
