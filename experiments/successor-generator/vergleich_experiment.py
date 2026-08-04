#! /usr/bin/env python

import itertools
import os
import sys
from collections import OrderedDict

from downward import suites
from downward.experiment import FastDownwardExperiment, FastDownwardRun
from lab import tools
from lab.parser import Parser
from lab.reports import Attribute, arithmetic_mean

import project

REPO = project.get_repo_base()
REVISION = "sg-marking"
SCP_LOGIN = "oglakc0000@login.infai.org"
REMOTE_REPOS_DIR = "/infai/oglakc0000/projects"

ALLE_SG_VARIABLEN = [
    "DOWNWARD_SG_NAIVE",
    "DOWNWARD_SG_WATCHED_LITERALS",
    "DOWNWARD_SG_MARKING",
]

SG_METHODEN = [
    ("baum", [], "match tree"),
    ("naiv", ["DOWNWARD_SG_NAIVE=1"], "naive"),
    ("watched", ["DOWNWARD_SG_WATCHED_LITERALS=1"], "watched literals"),
    ("marking", ["DOWNWARD_SG_MARKING=1"], "marking"),
]

KONFIGURATIONEN = [
    ("astar-blind", ["--search", "astar(blind())"]),
    ("greedy-ff", ["--search", "eager_greedy([ff()])"]),
]

DOMAINS = [
    "airport", "blocks", "depot", "driverlog", "elevators-opt08-strips",
    "freecell", "grid", "gripper", "logistics00", "miconic", "movie",
    "mprime", "nomystery-opt11-strips", "openstacks-opt08-strips",
    "parcprinter-08-strips", "pegsol-08-strips", "pipesworld-notankage",
    "psr-small", "rovers", "satellite", "scanalyzer-08-strips",
    "sokoban-opt08-strips", "tpp", "transport-opt08-strips", "trucks-strips",
    "visitall-opt11-strips", "woodworking-opt08-strips", "zenotravel",
]

AUFGABEN_PRO_DOMAIN = 6

BUILD_OPTIONS = ["-j4"]


def waehle_aufgaben(benchmarks_dir, domains, anzahl):
    ausgewaehlt = []
    for domain in domains:
        for aufgabe in suites.build_suite(benchmarks_dir, [domain])[:anzahl]:
            ausgewaehlt.append(f"{aufgabe.domain}:{aufgabe.problem}")
    return ausgewaehlt


if project.REMOTE:
    BENCHMARKS_DIR = os.environ["DOWNWARD_BENCHMARKS"]
    SUITE = waehle_aufgaben(BENCHMARKS_DIR, DOMAINS, AUFGABEN_PRO_DOMAIN)
    ENV = project.BaselSlurmEnvironment(email="d.oglakcioglu@unibas.ch")
    ZEITLIMIT = "5m"
else:
    BENCHMARKS_DIR = REPO / "misc" / "tests" / "benchmarks"
    SUITE = ["gripper", "miconic", "philosophers"]
    ENV = project.LocalEnvironment(processes=2)
    ZEITLIMIT = "60s"

DRIVER_OPTIONS = ["--overall-time-limit", ZEITLIMIT, "--search-memory-limit", "3500M"]


class SGRun(FastDownwardRun):
    def __init__(self, exp, algo, task, praefix, methode_nick):
        super().__init__(exp, algo, task)
        befehl, kwargs = self.commands["planner"]
        self.commands["planner"] = (praefix + befehl, kwargs)
        self.set_property("sg_methode", methode_nick)


class SGExperiment(FastDownwardExperiment):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sg_methoden = {}

    def add_sg_algorithm(self, name, methode_nick, zuweisungen, **kwargs):
        # lab haelt zwei Algorithmen fuer identisch, wenn Revision, Driver- und
        # Suchoptionen gleich sind - unsere drei Methoden unterscheiden sich nur
        # in der Umgebungsvariable. Deshalb versteckt der Tausch die schon
        # eingetragenen Algorithmen vor dieser Pruefung.
        vorhandene = self._algorithms
        self._algorithms = OrderedDict()
        super().add_algorithm(name, REPO, REVISION, **kwargs)
        algorithmus = self._algorithms[name]
        self._algorithms = vorhandene
        if name in self._algorithms:
            sys.exit(f"Algorithmusnamen muessen eindeutig sein: {name}")
        self._algorithms[name] = algorithmus

        praefix = ["env"]
        for variable in ALLE_SG_VARIABLEN:
            praefix += ["-u", variable]
        self.sg_methoden[name] = (methode_nick, praefix + zuweisungen)

    def _add_runs(self):
        aufgaben = self._get_tasks()
        for algo in self._algorithms.values():
            methode_nick, praefix = self.sg_methoden[algo.name]
            for aufgabe in aufgaben:
                self.add_run(SGRun(self, algo, aufgabe, praefix, methode_nick))


def get_parser():
    parser = Parser()
    parser.add_pattern(
        "generator_erstellungszeit_sekunden",
        r"time for successor generation creation: ([\d.]+)s",
        type=float,
    )
    parser.add_pattern(
        "generator_abfragezeit_sekunden",
        r"Time for successor generation: ([\d.]+)s",
        type=float,
    )
    parser.add_pattern(
        "generator_anzahl_abfragen",
        r"Successor generator calls: (\d+)",
        type=int,
    )
    parser.add_pattern(
        "generator_methode",
        r"Successor generator method: (.+)",
        type=str,
    )
    return parser


def uebersetze_und_berechne(run):
    run["uebersetzungszeit_sekunden"] = run.get("translator_time_done")
    run["suchzeit_sekunden"] = run.get("search_time")
    run["gesamtzeit_sekunden"] = run.get("total_time")
    run["aufgabe_geloest"] = run.get("coverage")
    run["anzahl_expandierte_zustaende"] = run.get("expansions")
    run["anzahl_bewertete_zustaende"] = run.get("evaluations")
    run["speicherverbrauch_kilobyte"] = run.get("memory")
    run["loesungskosten"] = run.get("cost")

    erstellung = run.get("generator_erstellungszeit_sekunden")
    abfrage = run.get("generator_abfragezeit_sekunden")
    abfragen = run.get("generator_anzahl_abfragen")
    expansionen = run.get("anzahl_expandierte_zustaende")
    suche = run.get("suchzeit_sekunden")
    gesamt = run.get("gesamtzeit_sekunden")
    uebersetzung = run.get("uebersetzungszeit_sekunden")

    if suche is not None and abfrage is not None:
        run["suchzeit_ohne_generator_sekunden"] = suche - abfrage
    if gesamt is not None and suche is not None and erstellung is not None:
        run["sonstige_planerzeit_sekunden"] = gesamt - suche - erstellung
    if uebersetzung is not None and gesamt is not None:
        run["gesamtzeit_mit_uebersetzung_sekunden"] = uebersetzung + gesamt

    if abfrage is not None and suche:
        run["generator_anteil_an_suchzeit"] = abfrage / suche
    if abfrage is not None and gesamt:
        run["generator_anteil_an_gesamtzeit"] = abfrage / gesamt
    if erstellung is not None and abfrage is not None and gesamt:
        run["generator_gesamtanteil_an_gesamtzeit"] = (erstellung + abfrage) / gesamt
    if suche is not None and gesamt:
        run["suchzeit_anteil_an_gesamtzeit"] = suche / gesamt

    if abfrage is not None and abfragen:
        run["zeit_pro_abfrage_mikrosekunden"] = abfrage / abfragen * 1000000
    if abfragen is not None and expansionen:
        run["abfragen_pro_expansion"] = abfragen / expansionen

    return run


ERWARTETE_AUSGABE = {nick: ausgabe for nick, _, ausgabe in SG_METHODEN}


def pruefe_methode(run):
    gemessen = run.get("generator_methode")
    if gemessen is not None:
        erwartet = ERWARTETE_AUSGABE[run["sg_methode"]]
        if gemessen.strip() != erwartet:
            tools.add_unexplained_error(
                run, f"erwartet war '{erwartet}', gelaufen ist '{gemessen.strip()}'"
            )
    return True


def _sekunden(name, digits=4):
    return Attribute(name, min_wins=True, function=arithmetic_mean, digits=digits)


def _anteil(name, digits=4):
    return Attribute(name, min_wins=False, function=arithmetic_mean, digits=digits)


ZEIT_ATTRIBUTE = [
    _sekunden("uebersetzungszeit_sekunden"),
    _sekunden("generator_erstellungszeit_sekunden"),
    _sekunden("generator_abfragezeit_sekunden"),
    _sekunden("zeit_pro_abfrage_mikrosekunden"),
    _sekunden("suchzeit_ohne_generator_sekunden"),
    _sekunden("sonstige_planerzeit_sekunden"),
    _sekunden("suchzeit_sekunden"),
    _sekunden("gesamtzeit_sekunden"),
    _sekunden("gesamtzeit_mit_uebersetzung_sekunden"),
]

ANTEIL_ATTRIBUTE = [
    _anteil("generator_anteil_an_suchzeit"),
    _anteil("generator_anteil_an_gesamtzeit"),
    _anteil("generator_gesamtanteil_an_gesamtzeit"),
    _anteil("suchzeit_anteil_an_gesamtzeit"),
    _anteil("abfragen_pro_expansion"),
]

ANZAHL_ATTRIBUTE = [
    "aufgabe_geloest",
    "loesungskosten",
    "anzahl_expandierte_zustaende",
    "anzahl_bewertete_zustaende",
    "generator_anzahl_abfragen",
    "speicherverbrauch_kilobyte",
]

ATTRIBUTES = [
    "error",
    "run_dir",
    "sg_methode",
    "generator_methode",
    *ANZAHL_ATTRIBUTE,
    *ZEIT_ATTRIBUTE,
    *ANTEIL_ATTRIBUTE,
]

SCATTER_ATTRIBUTE = [
    "generator_abfragezeit_sekunden",
    "zeit_pro_abfrage_mikrosekunden",
    "gesamtzeit_sekunden",
]


exp = SGExperiment(environment=ENV)

PAARE = []
for konfig_nick, konfig in KONFIGURATIONEN:
    namen = []
    for methode_nick, zuweisungen, _ in SG_METHODEN:
        algo_name = f"{konfig_nick}-{methode_nick}"
        exp.add_sg_algorithm(
            algo_name,
            methode_nick,
            zuweisungen,
            component_options=konfig,
            build_options=BUILD_OPTIONS,
            driver_options=DRIVER_OPTIONS,
        )
        namen.append(algo_name)
    PAARE += [(namen[0], namen[1]), (namen[0], namen[2]), (namen[1], namen[2])]

exp.add_suite(BENCHMARKS_DIR, SUITE)

exp.add_parser(exp.EXITCODE_PARSER)
exp.add_parser(exp.TRANSLATOR_PARSER)
exp.add_parser(exp.SINGLE_SEARCH_PARSER)
exp.add_parser(get_parser())
exp.add_parser(exp.PLANNER_PARSER)

exp.add_step("build", exp.build)
exp.add_step("start", exp.start_runs)
exp.add_step("parse", exp.parse)
exp.add_fetcher(name="fetch")

project.add_absolute_report(
    exp,
    name=f"{exp.name}-alle",
    attributes=ATTRIBUTES,
    filter=[uebersetze_und_berechne, pruefe_methode],
)

# Eine Tabelle beruecksichtigt nur Aufgaben, die alle ihre Algorithmen geloest
# haben. Ein fehlerhafter Generator wuerde die Tabelle mit allen Methoden also
# leeren. Diese Berichte je Methodenpaar bleiben davon unberuehrt.
methoden = [methode for methode, _, _ in SG_METHODEN]
for erste, zweite in itertools.combinations(methoden, 2):
    project.add_absolute_report(
        exp,
        name=f"{exp.name}-{erste}-vs-{zweite}",
        attributes=ATTRIBUTES,
        filter=[uebersetze_und_berechne, pruefe_methode],
        filter_algorithm=[
            f"{konfig_nick}-{methode}"
            for konfig_nick, _ in KONFIGURATIONEN
            for methode in (erste, zweite)
        ],
    )

project.add_scatter_plot_reports(
    exp, PAARE, SCATTER_ATTRIBUTE, filter=[uebersetze_und_berechne]
)

if not project.REMOTE:
    project.add_scp_step(exp, SCP_LOGIN, REMOTE_REPOS_DIR)

exp.run_steps()
