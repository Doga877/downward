#! /usr/bin/env python

import os

from lab.parser import Parser
from lab.reports import Attribute, arithmetic_mean

import project

REPO = project.get_repo_base()
BENCHMARKS_DIR = os.environ["DOWNWARD_BENCHMARKS"]
SCP_LOGIN = "oglakc0000@login.infai.org"
REMOTE_REPOS_DIR = "/infai/oglakc0000/projects"

os.environ["DOWNWARD_SG_NAIVE"] = "1"

if project.REMOTE:
    SUITE = project.SUITE_SATISFICING
    ENV = project.BaselSlurmEnvironment(email="d.oglakcioglu@unibas.ch")
else:
    SUITE = ["depot:p01.pddl", "grid:prob01.pddl", "gripper:prob01.pddl"]
    ENV = project.LocalEnvironment(processes=2)

HEURISTICS = [
    ("blind", "blind()"),
    ("add", "add(transform=adapt_costs(one))"),
]

SEARCH_ALGORITHMS = [
    ("astar", lambda h: f"astar({h})"),
    ("eager_greedy", lambda h: f"eager_greedy([{h}])"),
    ("lazy_greedy", lambda h: f"lazy_greedy([{h}])"),
]

CONFIGS = [
    (f"{algo_nick}-{h_nick}", ["--search", make_search(h)])
    for algo_nick, make_search in SEARCH_ALGORITHMS
    for h_nick, h in HEURISTICS
]

BUILD_OPTIONS = ["-j4"]
DRIVER_OPTIONS = ["--overall-time-limit", "5m", "--search-memory-limit", "3500M"]

REV_NICKS = [("sg-naive", "")]


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

    return run


def _sekunden(name, digits=4):
    return Attribute(name, min_wins=True, function=arithmetic_mean, digits=digits)


def _anteil(name, digits=4):
    return Attribute(name, min_wins=False, function=arithmetic_mean, digits=digits)


ZEIT_ATTRIBUTE = [
    _sekunden("uebersetzungszeit_sekunden"),
    _sekunden("generator_erstellungszeit_sekunden"),
    _sekunden("generator_abfragezeit_sekunden"),
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
    "generator_methode",
    *ANZAHL_ATTRIBUTE,
    *ZEIT_ATTRIBUTE,
    *ANTEIL_ATTRIBUTE,
]


exp = project.FastDownwardExperiment(environment=ENV)
for config_nick, config in CONFIGS:
    for rev, rev_nick in REV_NICKS:
        algo_name = f"{rev_nick}:{config_nick}" if rev_nick else config_nick
        exp.add_algorithm(
            algo_name,
            REPO,
            rev,
            config,
            build_options=BUILD_OPTIONS,
            driver_options=DRIVER_OPTIONS,
        )
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
    attributes=ATTRIBUTES,
    filter=[uebersetze_und_berechne],
)

if not project.REMOTE:
    project.add_scp_step(exp, SCP_LOGIN, REMOTE_REPOS_DIR)

exp.run_steps()
