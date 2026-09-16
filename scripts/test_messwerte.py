#!/usr/bin/env python3
"""
Tests für scripts/messwerte.py.

    python scripts/test_messwerte.py

Kein Netzzugriff: Der HTTP-Aufruf wird ersetzt, die Antworten sind hier
nachgebaut. Getestet wird, was ohne Netzzugang zu AVAMET prüfbar ist —
also genau die Stellen, an denen ein Fehler stumm bliebe.

Das Skript nutzt nur die Standardbibliothek, deshalb auch dieser Test.
"""

import importlib.util
import io
import os
import sys
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
# Die Rose der App: Grad rein, deutsches Kuerzel raus. Die spanische Tabelle
# daneben gibt es nicht mehr - AEMET ist am 16.09.2026 aus dem Job geflogen.
pruefe("deutsches O ist Osten", mw.compass(90), "O")
pruefe("deutsches SO ist Suedosten", mw.compass(135), "SO")
pruefe("270 Grad ist im Deutschen W", mw.compass(270), "W")
pruefe("compass ohne Wert", mw.compass(None), None)
pruefe("compass rechnet ueber 360 hinaus", mw.compass(361), "N")

# -------------------------------------------------------------- rechne_bias
print("\nrechne_bias:")


def paare(stunde, anzahl, diff, station=mw.BIAS_STATION):
    """anzahl Messpaare zur gegebenen Stunde, jeweils mit der Abweichung diff."""
    return [{"zeit": f"2026-09-{10 + i % 20:02d}T{stunde:02d}:{i * 5 % 60:02d}+02:00",
             "station": station,
             "gemessen_kn": f"{10 + diff:.1f}",
             "arome_kn": "10.0"} for i in range(anzahl)]


pruefe("keine Zeilen", mw.rechne_bias([]), {})
pruefe("fremde Station zaehlt nicht",
       mw.rechne_bias(paare(19, 40, -5, "Cullera Faro")), {})
pruefe("unter der Mindestzahl bleibt die Stunde draussen",
       mw.rechne_bias(paare(19, mw.BIAS_MIN_STUNDE - 1, -5)), {})
pruefe("genau die Mindestzahl reicht",
       mw.rechne_bias(paare(19, mw.BIAS_MIN_STUNDE, -5)),
       {"19": {"kn": -5.0, "n": mw.BIAS_MIN_STUNDE}})

# Der Kern: jede Stunde nur mit ihrer eigenen Stichprobe. Die duenne Stunde
# bekommt KEINEN Ersatzwert – frueher war das der Median ueber alle Stunden,
# und der liegt zwischen Vormittagsplus und Abendminus, also in beiden falsch.
gemischt = mw.rechne_bias(paare(12, 10, +4.5) + paare(19, 10, -5.0) + paare(20, 3, -5.0))
pruefe("Vormittag mit eigenem Vorzeichen", gemischt["12"]["kn"], 4.5)
pruefe("Abend mit eigenem Vorzeichen", gemischt["19"]["kn"], -5.0)
pruefe("duenne Stunde taucht gar nicht auf", "20" in gemischt, False)
pruefe("kein Sammelwert fuer den Rest", sorted(gemischt), ["12", "19"])

pruefe("Ausreisser wird gedeckelt",
       mw.rechne_bias(paare(19, 10, -40))["19"]["kn"], -mw.BIAS_CAP)
pruefe("Median statt Mittel: ein Ausreisser kippt nichts",
       mw.rechne_bias(paare(19, 9, -2) + paare(19, 1, -40))["19"]["kn"], -2.0)
pruefe("kaputte Zeilen werden uebersprungen",
       mw.rechne_bias(paare(19, 8, -3) + [{"zeit": "x", "station": mw.BIAS_STATION,
                                           "gemessen_kn": "", "arome_kn": ""}])["19"]["n"], 8)

# -------------------------------------------------- Paarung Messung/Prognose
print("\nPaarung Messung – Prognose:")
pruefe("stunde_von schneidet auf die volle Stunde",
       mw.stunde_von("2026-09-15T13:54+02:00"), "2026-09-15T13:00")
pruefe("stunde_von kurz nach Mitternacht",
       mw.stunde_von("2026-09-15T00:05+02:00"), "2026-09-15T00:00")

HD = mw.LEITMODELL
stundenreihe = {
    "time": ["2026-09-11T11:00", "2026-09-11T12:00"],
    f"wind_speed_10m_{HD}": [3.3, 1.0],
    f"wind_gusts_10m_{HD}": [8.4, 8.7],
    f"wind_direction_10m_{HD}": [298, 338],
}
# Der echte Fall vom 11.09.2026: gemessen 11:59, abgeholt 12:02. Richtig ist
# der 11-Uhr-Wert 3,3 kn – der alte Code nahm den 12-Uhr-Wert 1,0 kn.
elf = mw.prognosen_fuer(stundenreihe, mw.stunde_von("2026-09-11T11:59+02:00"))
pruefe("Messung 11:59 bekommt die 11-Uhr-Prognose", elf[HD]["kn"], 3.3)
pruefe("... die Folgestunde hat einen anderen Wert",
       mw.prognosen_fuer(stundenreihe, "2026-09-11T12:00")[HD]["kn"], 1.0)
pruefe("Boe und Richtung kommen mit", elf[HD], {"kn": 3.3, "boe": 8.4, "grad": 298})
pruefe("Stunde nicht in der Antwort -> leer",
       mw.prognosen_fuer(stundenreihe, "2026-09-11T13:00"), {})
pruefe("keine Antwort -> leer", mw.prognosen_fuer(None, "2026-09-11T11:00"), {})
pruefe("kaputte Antwort -> leer", mw.prognosen_fuer({"x": 1}, "2026-09-11T11:00"), {})
pruefe("Modell ohne Wert faellt raus",
       mw.prognosen_fuer({"time": ["2026-09-11T11:00"], f"wind_speed_10m_{HD}": [None]},
                         "2026-09-11T11:00"), {})
pruefe("Vorstunden werden mitgeholt (past_days=1)", "past_days=1" in mw.PROGNOSE_URL, True)

# ---------------------------------------------------------------- Konsistenz
print("\nKonsistenz:")
pruefe("Leitmodell ist das erste Modell", mw.LEITMODELL, mw.WIND_MODELS[0])
pruefe("jedes Modell hat einen Kurznamen",
       sorted(mw.KURZNAME) == sorted(mw.WIND_MODELS), True)
# Die eigene Rose muss alle 16 Punkte treffen - sie beschriftet jede Messzeile.
pruefe("alle 16 Rosenpunkte", len({mw.compass(g) for g in range(0, 360, 1)}), 16)

print(f"\n{fehler} Test(s) fehlgeschlagen" if fehler else "\nAlle Tests bestanden")
sys.exit(1 if fehler else 0)
