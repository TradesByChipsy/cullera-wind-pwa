#!/usr/bin/env node
/**
 * Tests für die reinen Rechenfunktionen aus index.html.
 *
 *     node scripts/test_app.mjs
 *
 * Die App ist bewusst eine einzelne HTML-Datei ohne Build-Schritt. Damit die
 * Funktionen trotzdem testbar bleiben, schneidet dieser Test sie per Regex aus
 * dem <script>-Block heraus und lädt sie als Modul. Es wird also der echte
 * Quelltext geprüft, keine Kopie, die auseinanderdriften könnte.
 *
 * Getestet wird nur, was ohne Netz und ohne DOM auskommt: buildBias,
 * buildNowcast, ensembleFor, aemetFor. Alles andere hängt an Open-Meteo oder am
 * Rendering und gehört in einen Durchlauf im Browser.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const HIER = path.dirname(fileURLToPath(import.meta.url));
const INDEX = path.join(HIER, "..", "index.html");

// Die Datei liegt je nach Checkout mit CRLF vor – die Muster unten erwarten \n.
const quelle = fs.readFileSync(INDEX, "utf8").split("\r").join("");

function schnipsel(muster, name) {
  const t = quelle.match(muster);
  if (!t) throw new Error(`Im Quelltext nicht gefunden: ${name}. ` +
    `Wurde die Funktion umbenannt oder umformatiert? Dann hier das Muster nachziehen.`);
  return t[0];
}

const code = [
  schnipsel(/const BIAS_MODEL_ID[^\n]*\n/, "BIAS_MODEL_ID"),
  schnipsel(/const ENSEMBLE_MODEL[\s\S]*?const NOWCAST_MODELS = \[[\s\S]*?\];/, "Nowcast-Konstanten"),
  schnipsel(/function buildBias\(daten\)\{[\s\S]*?\n\}\n/, "buildBias"),
  schnipsel(/function buildNowcast\(raw\)\{[\s\S]*?\n\}\n/, "buildNowcast"),
  schnipsel(/function ensembleFor\([\s\S]*?\n\}\n/, "ensembleFor"),
  schnipsel(/function aemetFor\([\s\S]*?\n\}\n/, "aemetFor"),
].join("\n") + "\nexport {buildBias, buildNowcast, ensembleFor, aemetFor};";

const m = await import("data:text/javascript," + encodeURIComponent(code));

let fehler = 0;
const pruefe = (name, ist, soll) => {
  const gut = Object.is(ist, soll);
  if (!gut) fehler++;
  console.log(`  ${gut ? "ok  " : "FEHL"}  ${name.padEnd(52)}${gut ? "" : `soll ${soll}, ist ${ist}`}`);
};

// ---------------------------------------------------------------- buildBias
// Die App rechnet den Bias nicht mehr selbst – sie liest data/bias.json, das der
// Actions-Job fertig ablegt (siehe rechne_bias in messwerte.py, dort getestet).
// Hier wird nur geprueft, dass die App die Datei richtig auslegt und jede
// kaputte Form ueberlebt.
console.log("buildBias:");
pruefe("null", m.buildBias(null), null);
pruefe("leeres Objekt", m.buildBias({}), null);
pruefe("stunden fehlt", m.buildBias({station: "X"}), null);
pruefe("stunden ist kein Objekt", m.buildBias({stunden: "kaputt"}), null);
pruefe("stunden leer -> keine Korrektur", m.buildBias({stunden: {}}), null);
pruefe("Eintrag ohne Zahl wird verworfen",
  m.buildBias({stunden: {"19": {kn: null, n: 9}}}), null);
pruefe("Eintrag mit Text statt Zahl wird verworfen",
  m.buildBias({stunden: {"19": {kn: "viel", n: 9}}}), null);

// Der Kern des Ganzen: Nur Stunden aus der Datei werden verschoben, alle
// anderen laufen unveraendert durch. Frueher bekamen sie den Median ueber alle
// Stunden – bei +4,5 kn vormittags und -5 kn abends ist der in beiden Haelften
// falsch und taeuscht eine Eichung vor, die nicht stattgefunden hat.
const b = m.buildBias({
  station: "Cullera Marenyet",
  modell: "meteofrance_arome_france_hd",
  stunden: {"19": {kn: -5, n: 10}, "12": {kn: 4.5, n: 8}},
});
pruefe("Stunde aus der Datei ist geeicht", b.hat(19), true);
pruefe("... und liefert ihren eigenen Wert", b.delta(19), -5);
pruefe("zweite Stunde mit eigenem Vorzeichen", b.delta(12), 4.5);
pruefe("Stunde, die nicht drinsteht, bleibt ungeeicht", b.hat(20), false);
pruefe("... und wird NICHT verschoben", b.delta(20), 0);
pruefe("Referenzstation aus der Datei", b.station, "Cullera Marenyet");
pruefe("Modell aus der Datei", b.modell, "meteofrance_arome_france_hd");
pruefe("Stichprobengroesse der Stunde", b.perHourN[19], 10);
pruefe("Station fehlt -> Platzhalter statt Absturz",
  m.buildBias({stunden: {"19": {kn: -5, n: 10}}}).station, "Messstation");

// -------------------------------------------------------------- buildNowcast
console.log("\nbuildNowcast:");
const nc = (hd, normal) => ({minutely_15: {
  time: ["2026-09-10T17:00", "2026-09-10T17:15"],
  ...(hd ? {"wind_speed_10m_meteofrance_arome_france_hd_15min": hd} : {}),
  ...(normal ? {"wind_speed_10m_meteofrance_arome_france_15min": normal} : {}),
}});
pruefe("null", m.buildNowcast(null), null);
pruefe("leeres Objekt", m.buildNowcast({}), null);
pruefe("keine Modellreihen", m.buildNowcast({minutely_15: {time: ["a"]}}), null);
pruefe("HD vorhanden -> HD fuehrt", m.buildNowcast(nc([9, 9], [7, 7]))?.name, "AROME HD");
pruefe("HD leer -> Rueckfall auf 2,5 km", m.buildNowcast(nc([null, null], [7, 8]))?.name, "AROME");
pruefe("beide leer -> null", m.buildNowcast(nc([null, null], [null, null])), null);
pruefe("Luecken werden uebersprungen", m.buildNowcast(nc(null, [5, null]))?.schritte.length, 1);

// --------------------------------------------------------------- ensembleFor
console.log("\nensembleFor:");
const zeiten = [], mitglieder = {};
for (let h = 0; h < 24; h++) zeiten.push(`2026-09-11T${String(h).padStart(2, "0")}:00`);
// Mitglied k erreicht im Fenster 10 + k*0.25 kn: 24 der 40 liegen bei >= 14.
for (let k = 0; k < 40; k++)
  mitglieder["wind_speed_10m_member" + k] = zeiten.map((_, h) => (h >= 15 && h <= 20) ? 10 + k * 0.25 : 3);
const ens = {hourly: {time: zeiten, ...mitglieder}};
pruefe("null", m.ensembleFor(null, "2026-09-11", 15, 20), null);
pruefe("ohne hourly", m.ensembleFor({}, "2026-09-11", 15, 20), null);
pruefe("Tag nicht enthalten", m.ensembleFor(ens, "2030-01-01", 15, 20), null);
pruefe("40 Mitglieder erkannt", m.ensembleFor(ens, "2026-09-11", 15, 20).n, 40);
pruefe("Chance = Anteil ueber der Schwelle", m.ensembleFor(ens, "2026-09-11", 15, 20).chance, 60);
pruefe("zu wenige Mitglieder -> null", m.ensembleFor(
  {hourly: {time: zeiten, "wind_speed_10m_a": zeiten.map(() => 9), "wind_speed_10m_b": zeiten.map(() => 9)}},
  "2026-09-11", 15, 20), null);
pruefe("alle Werte null -> null", m.ensembleFor({hourly: {time: zeiten,
  ...Object.fromEntries(Array.from({length: 40}, (_, k) => ["wind_speed_10m_m" + k, zeiten.map(() => null)]))}},
  "2026-09-11", 15, 20), null);

// ------------------------------------------------------------------ aemetFor
console.log("\naemetFor:");
const A = {stunden: [
  {zeit: "2026-09-11T15:00", kn: 5.4, grad: 135},
  {zeit: "2026-09-11T17:00", kn: 11.9, grad: 135},
  {zeit: "2026-09-11T22:00", kn: 20, grad: 0},   // ausserhalb des Fensters
]};
pruefe("null", m.aemetFor(null, "2026-09-11", 15, 20), null);
pruefe("ohne stunden-Array", m.aemetFor({}, "2026-09-11", 15, 20), null);
pruefe("stunden ist kein Array", m.aemetFor({stunden: "kaputt"}, "2026-09-11", 15, 20), null);
pruefe("Tag ohne Treffer", m.aemetFor(A, "2026-09-13", 15, 20), null);
pruefe("Spitze im Fenster, 22 Uhr bleibt draussen", m.aemetFor(A, "2026-09-11", 15, 20).peak, 11.9);
pruefe("Spitzenstunde", m.aemetFor(A, "2026-09-11", 15, 20).stunde, 17);
pruefe("Richtung als Grad, nicht als Kuerzel", m.aemetFor(A, "2026-09-11", 15, 20).grad, 135);

console.log(fehler ? `\n${fehler} Test(s) fehlgeschlagen` : "\nAlle Tests bestanden");
process.exit(fehler ? 1 : 0);
