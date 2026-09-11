#!/usr/bin/env python3
"""
Tests für scripts/messwerte.py.

    python scripts/test_messwerte.py

Kein Netzzugriff: Der HTTP-Aufruf wird ersetzt, die Antworten sind hier
nachgebaut. Getestet wird, was ohne AVAMET und ohne AEMET-Schlüssel prüfbar ist —
also genau die Stellen, an denen ein Fehler stumm bliebe.

Das Skript nutzt nur die Standardbibliothek, deshalb auch dieser Test.
"""

import importlib.util
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout

HIER = os.path.dirname(os.path.abspath(__file__))

spec = importlib.util.spec_from_file_location("mw", os.path.join(HIER, "messwerte.py"))
mw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mw)

fehler = 0


def pruefe(name, ist, soll):
    global fehler
    gut = ist == soll
    if not gut:
        fehler += 1
    hinweis = "" if gut else f"soll {soll!r}, ist {ist!r}"
    print(f"  {'ok  ' if gut else 'FEHL'}  {name:<54}{hinweis}")


def leise(fn, *a, **kw):
    """Das Skript redet viel – für die Tests interessiert nur der Rückgabewert."""
    with redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


# ----------------------------------------------------------- Kompass / Grad
print("Richtungen:")
# Der teuerste Fehler des Projekts wäre, spanische und deutsche Kürzel zu
# verwechseln: AEMETs O ist Westen, das deutsche O ist Osten. Beide Tabellen
# liegen in derselben Datei, deshalb hier festgenagelt.
pruefe("AEMET O ist Westen (Oeste)", mw.AEMET_GRAD["O"], 270)
pruefe("AEMET SO ist Suedwesten (Suroeste)", mw.AEMET_GRAD["SO"], 225)
pruefe("AEMET E ist Osten (Este)", mw.AEMET_GRAD["E"], 90)
pruefe("deutsches O ist Osten", mw.compass(90), "O")
pruefe("deutsches SO ist Suedosten", mw.compass(135), "SO")
pruefe("270 Grad ist im Deutschen W", mw.compass(270), "W")
pruefe("compass ohne Wert", mw.compass(None), None)
pruefe("compass rechnet ueber 360 hinaus", mw.compass(361), "N")
pruefe("die beiden Tabellen sind NICHT deckungsgleich",
       mw.AEMET_GRAD["O"] == 90, False)

# ------------------------------------------------------------- _erste_zahl
print("\n_erste_zahl:")
pruefe("normale Liste", mw._erste_zahl(["12"]), 12.0)
pruefe("mit Leerzeichen", mw._erste_zahl([" 7 "]), 7.0)
pruefe("leere Liste", mw._erste_zahl([]), None)
pruefe("None", mw._erste_zahl(None), None)
pruefe("unparsbar", mw._erste_zahl(["kaputt"]), None)
pruefe("erster Wert unparsbar, zweiter gut", mw._erste_zahl(["x", "9"]), 9.0)

# ------------------------------------------------------------- avamet_time
print("\navamet_time:")
# AVAMET kodiert Ortszeit als waere sie UTC. Wer das normal liest, haelt frische
# Messungen fuer Vorhersagen aus der Zukunft.
t = mw.avamet_time(1757520000000)  # 2026-09-10T16:00 "UTC" = 16:00 Ortszeit
pruefe("Stunde bleibt die Ortszeit-Stunde", t.hour, 16)
pruefe("Zone ist Europe/Madrid", str(t.tzinfo), "Europe/Madrid")

# ----------------------------------------------------------- aemet_prognose
print("\naemet_prognose:")
META = {"descripcion": "exito", "estado": 200,
        "datos": "https://opendata.aemet.es/opendata/sh/abc123"}
# Wind und Boee stehen in DERSELBEN Liste, unterschieden nur durch
# velocidad gegen value. Genau so liefert AEMET es wirklich.
DATEN = [{"nombre": "Cullera", "prediccion": {"dia": [
    {"fecha": "2026-09-11T00:00:00", "vientoAndRachaMax": [
        {"direccion": ["O"], "velocidad": ["18.52"], "periodo": "09"},
        {"value": "37.04", "periodo": "09"},
        {"direccion": ["SE"], "velocidad": ["18.52"], "periodo": "17"},
        {"direccion": [], "velocidad": [], "periodo": "20"},
        {"direccion": ["E"], "velocidad": ["kaputt"], "periodo": "21"},
        {"direccion": ["C"], "velocidad": ["0"], "periodo": "22"},
    ]},
]}}]


def mit_antwort(meta=META, daten=DATEN, key="TEST"):
    os.environ["AEMET_API_KEY"] = key

    def fake(url, timeout=30):
        if "opendata.aemet.es/opendata/api" in url:
            return json.dumps(meta).encode()
        return json.dumps(daten).encode()
    mw.fetch = fake
    return leise(mw.aemet_prognose)


r = mit_antwort()
# Erwartet bleiben 09, 17 und 22 Uhr. Periode 20 hat leere Listen und erzeugt
# deshalb gar keine Stunde; Periode 21 hat eine unparsbare Geschwindigkeit und
# fliegt beim Umrechnen raus. Beides ist richtig so: Lieber keine Stunde als
# eine mit erfundenem Wert.
pruefe("gueltige Antwort liefert Stunden", len(r["stunden"]), 3)
pruefe("Westwind wird zu 270 Grad", r["stunden"][0]["grad"], 270)
pruefe("18,52 km/h sind 10,0 kn", r["stunden"][0]["kn"], 10.0)
pruefe("Boee der gleichen Periode zugeordnet", r["stunden"][0]["boe_kn"], 20.0)
pruefe("Stunde ohne Boee bleibt None", r["stunden"][1]["boe_kn"], None)
pruefe("leere und unparsbare Eintraege fallen raus",
       [s["zeit"][11:13] for s in r["stunden"]], ["09", "17", "22"])
pruefe("calma hat keine Richtung", r["stunden"][2]["grad"], None)
pruefe("calma behaelt aber die Windstille", r["stunden"][2]["kn"], 0.0)

print("\naemet_prognose – Ausfallpfade:")
for name, kw in [
    ("kein Schluessel", {"key": ""}),
    ("estado 401", {"meta": {"estado": 401, "descripcion": "API key invalido"}}),
    ("leere Vorhersage", {"daten": [{"prediccion": {"dia": []}}]}),
    ("fremde Struktur", {"daten": {"unerwartet": True}}),
]:
    pruefe(name, mit_antwort(**kw), None)


def mit_fehler(exc):
    os.environ["AEMET_API_KEY"] = "TEST"

    def fake(url, timeout=30):
        raise exc
    mw.fetch = fake
    return leise(mw.aemet_prognose)


pruefe("Netzfehler", mit_fehler(OSError("timeout")), None)
pruefe("kaputtes JSON", mit_fehler(ValueError("Expecting value")), None)

# --------------------------------------------------------- aemet_ist_frisch
print("\naemet_ist_frisch:")
from datetime import datetime, timedelta  # noqa: E402  (erst hier gebraucht)

with tempfile.TemporaryDirectory() as tmp:
    mw.AEMET_PATH = os.path.join(tmp, "aemet.json")
    pruefe("keine Datei -> nicht frisch", leise(mw.aemet_ist_frisch), False)

    def schreibe(minuten_alt):
        stand = datetime.now(mw.TZ) - timedelta(minutes=minuten_alt)
        with open(mw.AEMET_PATH, "w", encoding="utf-8") as f:
            json.dump({"stand": stand.isoformat(timespec="minutes")}, f)

    schreibe(5)
    pruefe("5 Minuten alt -> frisch, kein Abruf", leise(mw.aemet_ist_frisch), True)
    schreibe(mw.AEMET_SCHONFRIST_MIN + 5)
    pruefe("aelter als die Schonfrist -> neu holen", leise(mw.aemet_ist_frisch), False)
    with open(mw.AEMET_PATH, "w", encoding="utf-8") as f:
        f.write("{kaputt")
    pruefe("kaputte Datei -> neu holen", leise(mw.aemet_ist_frisch), False)

# ---------------------------------------------------------------- Konsistenz
print("\nKonsistenz:")
pruefe("Leitmodell ist das erste Modell", mw.LEITMODELL, mw.WIND_MODELS[0])
pruefe("jedes Modell hat einen Kurznamen",
       sorted(mw.KURZNAME) == sorted(mw.WIND_MODELS), True)
pruefe("alle 16 Rosenpunkte in AEMET_GRAD", len(mw.AEMET_GRAD), 16)

print(f"\n{fehler} Test(s) fehlgeschlagen" if fehler else "\nAlle Tests bestanden")
sys.exit(1 if fehler else 0)
