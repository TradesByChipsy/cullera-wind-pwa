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
 * Getestet wird, was ohne Netz und ohne DOM auskommt: buildBias, buildNowcast,
 * und der ganze Rechenweg einer Tageskarte (aggregate) mit
 * nachgebauten API-Antworten. Nur das Rendering bleibt dem Blick in den Browser.
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
  schnipsel(/const LAT = [\s\S]*?const WAVE_MODELS = \[[\s\S]*?\];/, "Konstanten + sessionWindow"),
  schnipsel(/const mean = a => \{[\s\S]*?\n\};/, "mean"),
  schnipsel(/const circMean = degs => \{[\s\S]*?\n\};/, "circMean"),
  schnipsel(/function seriesFor\([\s\S]*?\n\}\n/, "seriesFor"),
  schnipsel(/function windowIdx\([\s\S]*?\n\}\n/, "windowIdx"),
  schnipsel(/function aggregate\([\s\S]*?\n\}\n/, "aggregate"),
  schnipsel(/function realitaetsCheck\([\s\S]*?\n\}\n/, "realitaetsCheck"),
  schnipsel(/function messAlterMin\([\s\S]*?\n\}\n/, "messAlterMin"),
  schnipsel(/function istVeraltet\([\s\S]*?\n\}\n/, "istVeraltet"),
  schnipsel(/function alterText\([\s\S]*?\n\}\n/, "alterText"),
  schnipsel(/const BIAS_MODEL_ID[^\n]*\n/, "BIAS_MODEL_ID"),
  schnipsel(/const MATRIX_MODELLE[\s\S]*?const NOWCAST_MODELS = \[[\s\S]*?\];/, "Anzeige-Konstanten"),
  schnipsel(/function buildBias\(daten\)\{[\s\S]*?\n\}\n/, "buildBias"),
  schnipsel(/function buildNowcast\(raw\)\{[\s\S]*?\n\}\n/, "buildNowcast"),
].join("\n") + "\nexport {buildBias, buildNowcast, aggregate, realitaetsCheck, messAlterMin, istVeraltet, alterText};";

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

// ------------------------------------------------------------------ aggregate
// Der Fall vom 15.09.2026: Die korrigierte Spitze lag um 17 Uhr, der hoechste
// Rohwert um 18 Uhr. Die Karte muss den Rohwert DER Stunde nennen, deren
// korrigierter Wert oben steht – sonst geht "roh + Korrektur" nicht auf.
// Getestet wird der ganze Rechenweg der Karte, nicht nur eine Hilfsfunktion:
// Genau diese Luecke hat den Fehler bis zum 15.09. durchrutschen lassen.
console.log();
console.log("aggregate – Korrekturzeile der Karte:");
const HD_ID = "meteofrance_arome_france_hd";
function tagDaten(rohJeStunde, korrekturen) {
  const time = [], sp = [], gu = [], dr = [];
  for (let st = 0; st < 24; st++) {
    time.push(`2026-09-15T${String(st).padStart(2, "0")}:00`);   // Dienstag: Fenster 15–20
    const v = rohJeStunde[st] ?? 3;
    sp.push(v); gu.push(v + 5); dr.push(110);
  }
  const stunden = Object.fromEntries(
    Object.entries(korrekturen).map(([h, kn]) => [h, {kn, n: 12}]));
  return {
    wind: {hourly: {time, [`wind_speed_10m_${HD_ID}`]: sp,
                    [`wind_gusts_10m_${HD_ID}`]: gu, [`wind_direction_10m_${HD_ID}`]: dr}},
    wave: {hourly: {time}},
    bias: m.buildBias({stunden}),
  };
}
const rund1 = x => x == null ? x : Math.round(x * 10) / 10;
const heuteRoh = {15: 9.7, 16: 10.8, 17: 11.3, 18: 13.6, 19: 11.8, 20: 11.5};

const k1 = m.aggregate(tagDaten(heuteRoh,
  {15: -0.4, 16: -1.0, 17: 0.7, 18: -1.9, 19: -3.2, 20: -4.5}))[0];
pruefe("korrigierte Spitze 12,0 kn", rund1(k1.windPeak), 12);
pruefe("... um 17 Uhr, nicht um 18", k1.peakHour, 17);
pruefe("Korrektur der Spitzenstunde", k1.biasDelta, 0.7);
pruefe("Rohwert aus DERSELBEN Stunde (11,3 statt 13,6)", k1.peakRaw, 11.3);
pruefe("roh + Korrektur = angezeigte Spitze", rund1(k1.peakRaw + k1.biasDelta), rund1(k1.windPeak));

// Spitzenstunde ungeeicht: keine Korrektur-Behauptung, Rohwert passt trotzdem
const k2 = m.aggregate(tagDaten(heuteRoh, {17: 0.7}))[0];
pruefe("ungeeichte 18-Uhr-Stunde bleibt vorn", k2.peakHour, 18);
pruefe("... dann keine Korrekturzeile", k2.biasDelta, null);
pruefe("... und der Rohwert ist der der Spitzenstunde", k2.peakRaw, 13.6);

// ganz ohne Korrektur: kein Rohwert-Hinweis
const k3 = m.aggregate(tagDaten(heuteRoh, {}))[0];
pruefe("ohne Korrektur: Spitze = hoechster Rohwert", k3.windPeak, 13.6);
pruefe("ohne Korrektur: kein peakRaw", k3.peakRaw, null);


// --------------------------------------------------------- Stundenmatrix
// Die Matrix ersetzt Kachelblock, Quellenliste und Gegenprobe: Wo die Modelle
// auseinanderlaufen, sieht man es an den Zahlen. Am 15.09.2026 zeigte die Karte
// 11,3 kn, ECMWF 8,7 und ICON-EU 8,3 - gemessen wurden ab 17 Uhr 4 bis 5.
console.log();
console.log("Stundenmatrix:");
function tagDrei(arome, ecmwf, icon) {
  const time = [];
  for (let st = 0; st < 24; st++) time.push(`2026-09-15T${String(st).padStart(2, "0")}:00`);
  const reihe = v => Array.from({length: 24}, (_, st) => v[st] ?? 3);
  const reihen = {};
  for (const [id, v] of [["meteofrance_arome_france_hd", arome],
                         ["ecmwf_ifs", ecmwf], ["icon_eu", icon]]) {
    reihen[`wind_speed_10m_${id}`] = reihe(v);
    reihen[`wind_gusts_10m_${id}`] = reihe(v).map(x => x + 5);
    reihen[`wind_direction_10m_${id}`] = reihe({}).map(() => 110);
  }
  return {wind: {hourly: {time, ...reihen}}, wave: {hourly: {time}},
          bias: null};
}

const mx = m.aggregate(tagDrei({17: 11.3, 18: 13.5}, {17: 8.7, 18: 8.9}, {17: 8.3, 18: 8.1}))[0];
pruefe("vier Modellzeilen", mx.matrix.length, 4);
pruefe("... in fester Reihenfolge", mx.matrix.map(r => r.name).join(","),
  "Arome HD,ECMWF,Icon-EU,GFS");
pruefe("Leitmodell ist markiert", mx.matrix[0].lead, true);
pruefe("... und nur dieses", mx.matrix.filter(r => r.lead).length, 1);
// Jede Modellzeile muss Spalte fuer Spalte zu hours passen, sonst stehen die
// Werte unter der falschen Stunde.
pruefe("Zeile so lang wie die Stundenreihe",
  mx.matrix[0].werte.length, mx.hours.length);
pruefe("Wert steht unter seiner Stunde",
  mx.matrix[1].werte[mx.hours.findIndex(h => +h.t.slice(11,13) === 17)], 8.7);
// GFS fehlt in diesen Testdaten - genau wie AROME ab dem dritten Tag.
pruefe("Modell ohne Daten -> werte null", mx.matrix[3].werte, null);

// Die Leiste beginnt vier Stunden vor dem Fenster (Mo-Fr 15-20 Uhr), nicht
// pauschal um 8: 13 Spalten sind auf dem Handy mehr Scrollweg als Nutzen.
pruefe("Leiste startet um 11 Uhr", +mx.hours[0].t.slice(11,13), 11);
pruefe("... und endet um 20 Uhr", +mx.hours[mx.hours.length-1].t.slice(11,13), 20);
pruefe("... also zehn Spalten", mx.hours.length, 10);
console.log();
console.log("Realitaetscheck im Messpanel:");
const heuteKarte = m.aggregate(tagDrei({17: 11.0}, {17: 10.5}, {17: 10.6}))[0];
// Die Uhr wird hereingereicht, sonst waeren die Messungen unten je nach
// Testzeitpunkt zu alt und jeder Hinweis bliebe aus.
const JETZT = new Date("2026-09-15T17:20+02:00").getTime();
const messung = (kn, veraltet = false, zeit = "2026-09-15T17:05+02:00") =>
  ({stationen: [{name: "Cullera Marenyet", kn, veraltet, gemessen: zeit}]});
pruefe("Modell 11, gemessen 5 -> Hinweis", m.realitaetsCheck(messung(5), heuteKarte, 17, JETZT)?.gemessen, 5);
pruefe("... und zwar: Modell zu hoch", m.realitaetsCheck(messung(5), heuteKarte, 17, JETZT)?.diff > 0, true);
pruefe("kleiner Unterschied -> kein Hinweis", m.realitaetsCheck(messung(9), heuteKarte, 17, JETZT), null);
pruefe("veraltete Messung -> kein Hinweis", m.realitaetsCheck(messung(5, true), heuteKarte, 17, JETZT), null);
pruefe("Stunde ohne Prognose -> kein Hinweis", m.realitaetsCheck(messung(5), heuteKarte, 3, JETZT), null);
pruefe("keine Messung -> kein Hinweis", m.realitaetsCheck(null, heuteKarte, 17, JETZT), null);
pruefe("Messung aus anderer Stunde -> kein Hinweis",
  m.realitaetsCheck(messung(5, false, "2026-09-15T15:29+02:00"), heuteKarte, 17, JETZT), null);
pruefe("Messung ohne Zeitstempel -> kein Hinweis",
  m.realitaetsCheck({stationen: [{name: "Cullera Marenyet", kn: 5}]}, heuteKarte, 17, JETZT), null);


console.log();
console.log("Alter der Messung:");
// Der Ausloeser: Am 16.09.2026 stand der Actions-Job seit 23:41 Uhr. Die Datei
// trug weiter veraltet=false, weil das Flag beim Schreiben gesetzt wird und
// nicht mitaltert – die App zeigte neun Stunden alte Werte als "jetzt gemessen".
const MORGENS = new Date("2026-09-16T09:04+02:00").getTime();
const gestern = {veraltet: false, gemessen: "2026-09-15T23:34+02:00"};
pruefe("Flag sagt frisch, Zeitstempel 9 Std alt -> veraltet",
  m.istVeraltet(gestern, MORGENS), true);
pruefe("... und das Alter wird beziffert",
  m.alterText(m.messAlterMin(gestern.gemessen, MORGENS)), "vor 9 Std");
pruefe("frische Messung -> nicht veraltet",
  m.istVeraltet({veraltet: false, gemessen: "2026-09-15T17:05+02:00"}, JETZT), false);
pruefe("Flag sagt veraltet -> veraltet, auch bei frischem Stempel",
  m.istVeraltet({veraltet: true, gemessen: "2026-09-15T17:05+02:00"}, JETZT), true);
pruefe("kein Zeitstempel -> veraltet", m.istVeraltet({veraltet: false}, JETZT), true);
pruefe("unlesbarer Zeitstempel -> veraltet",
  m.istVeraltet({veraltet: false, gemessen: "keine Zeit"}, JETZT), true);
pruefe("keine Station -> veraltet", m.istVeraltet(null, JETZT), true);
// Genau auf der Schwelle gilt die Messung noch.
const vorMin = min => ({veraltet: false,
  gemessen: new Date(JETZT - min * 60000).toISOString()});
pruefe("45 Min alt -> gilt noch", m.istVeraltet(vorMin(45), JETZT), false);
pruefe("46 Min alt -> veraltet", m.istVeraltet(vorMin(46), JETZT), true);
pruefe("Alter in Minuten", Math.round(m.messAlterMin("2026-09-15T17:05+02:00", JETZT)), 15);
pruefe("fehlender Stempel -> kein Alter", m.messAlterMin(null, JETZT), null);
pruefe("Text: Minuten", m.alterText(12), "vor 12 Min");
pruefe("Text: Stunden", m.alterText(200), "vor 3 Std");
pruefe("Text: Tage", m.alterText(2880), "vor 2 Tagen");
// Zwei Messungen eine Minute auseinander muessen dasselbe Alter zeigen.
pruefe("569 Min", m.alterText(569), "vor 9 Std");
pruefe("570 Min, gleiches Alter", m.alterText(570), "vor 9 Std");

// Die Stundenzahl allein kennt das Datum nicht: Eine Messung von gestern 09:34
// kaeme heute um 9 Uhr durch die alte Pruefung. Erst das Alter faengt sie ab.
// Stunde 12, weil die Leiste unter der Woche erst um 11 Uhr beginnt.
const MITTAGS = new Date("2026-09-16T12:04+02:00").getTime();
const karte12 = m.aggregate(tagDrei({12: 12.0}, {12: 11.5}, {12: 11.6}))[0];
const st12 = z => ({stationen: [{name: "Cullera Marenyet", kn: 5,
                                 veraltet: false, gemessen: z}]});
pruefe("Stunde liegt ueberhaupt in der Leiste",
  karte12.hours.some(h => +h.t.slice(11,13) === 12), true);
pruefe("gleiche Stunde, aber von gestern -> kein Hinweis",
  m.realitaetsCheck(st12("2026-09-15T12:34+02:00"), karte12, 12, MITTAGS), null);
pruefe("gleiche Stunde und frisch -> Hinweis",
  m.realitaetsCheck(st12("2026-09-16T12:34+02:00"), karte12, 12,
    new Date("2026-09-16T12:44+02:00").getTime())?.gemessen, 5);


console.log(fehler ? `\n${fehler} Test(s) fehlgeschlagen` : "\nAlle Tests bestanden");
process.exit(fehler ? 1 : 0);
