#! /usr/bin/env python

"""Korrektheitstest: mit sortierter Operatorliste muessen alle vier
Generatoren ziffernweise dieselbe Anzahl Expansionen liefern."""

import collections
import os
import shutil
import subprocess
import sys
from collections import OrderedDict

from downward import suites
from downward.experiment import FastDownwardExperiment, FastDownwardRun
from lab import tools
from lab.parser import Parser
from lab.reports import Attribute, arithmetic_mean

import project

REPO = project.get_repo_base()
REVISION = "testing-correctness"


def check_revision_exists(repo, revision):
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet",
         f"{revision}^{{commit}}"],
        capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"Revision '{revision}' not found in {repo}.")


check_revision_exists(REPO, REVISION)

ALL_GENERATOR_ENV_VARS = [
    "DOWNWARD_SG_NAIVE",
    "DOWNWARD_SG_WATCHED_LITERALS",
    "DOWNWARD_SG_MARKING",
    "DOWNWARD_SG_TIMER",
    "DOWNWARD_SG_SORT",
]

GENERATOR_METHODS = [
    ("match_tree", [], "match tree"),
    ("naive", ["DOWNWARD_SG_NAIVE=1"], "naive"),
    ("watched_literals", ["DOWNWARD_SG_WATCHED_LITERALS=1"], "watched literals"),
    ("marking", ["DOWNWARD_SG_MARKING=1"], "marking"),
]

SEARCH_CONFIGS = [
    ("astar-blind", ["--search", "astar(blind())"]),
    ("greedy-ff", ["--search", "eager_greedy([ff()])"]),
]

TIMER_MODES = [
    ("timer_off", "off"),
    ("timer_cpu", "cpu"),
]

# Sortierung immer an; ohne sie ist das Ergebnis aus Experiment 1 bekannt.
SORT_ASSIGNMENT = "DOWNWARD_SG_SORT=1"

BUILD_OPTIONS = ["-j4"]
MEMORY_LIMIT = "3584M"

CLUSTER_SETUP = "\n".join([
    "module purge",
    "module -q load GCC/13.2.0",
    "module -q load Python/3.11.5-GCCcore-13.2.0",
    "module -q load CMake/3.27.6-GCCcore-13.2.0",
])

# Domaenen, in denen die Expansionen in Experiment 1 am haeufigsten abwichen,
# plus miconic und pegsol als Gegenprobe (dort waren sie meist schon gleich).
SUITE_DOMAINS = [
    "blocks",
    "depot",
    "freecell",
    "hiking-opt14-strips",
    "logistics00",
    "logistics98",
    "miconic",
    "pegsol-08-strips",
    "pipesworld-notankage",
    "pipesworld-tankage",
    "rovers",
    "termes-opt18-strips",
    "trucks-strips",
    "zenotravel",
]
TASKS_PER_DOMAIN = 6

if project.REMOTE:
    BENCHMARKS_DIR = os.environ.get("DOWNWARD_BENCHMARKS")
    if not BENCHMARKS_DIR:
        sys.exit("Set DOWNWARD_BENCHMARKS to the downward-benchmarks checkout.")
    SUITE = SUITE_DOMAINS
    ENV = project.BaselSlurmEnvironment(
        partition="infai_2",
        qos="infai",
        memory_per_cpu="3872M",
        email="d.oglakcioglu@unibas.ch",
        setup=CLUSTER_SETUP,
    )
    TIME_LIMIT = "60s"
else:
    BENCHMARKS_DIR = REPO / "misc" / "tests" / "benchmarks"
    SUITE = ["gripper", "miconic", "philosophers"]
    ENV = project.LocalEnvironment(processes=2)
    TIME_LIMIT = "60s"

DRIVER_OPTIONS = [
    "--overall-time-limit", TIME_LIMIT,
    "--overall-memory-limit", MEMORY_LIMIT,
]

VALIDATE_PLANS = shutil.which("validate") is not None
if not VALIDATE_PLANS:
    print("VAL ('validate') not on PATH: running without plan validation.")


def select_tasks():
    """Je Domain nur die ersten TASKS_PER_DOMAIN Aufgaben, damit der Test
    in Minuten statt Stunden durchlaeuft."""
    tasks = suites.build_suite(BENCHMARKS_DIR, SUITE)
    seen = collections.Counter()
    selected = []
    for task in tasks:
        if seen[task.domain] < TASKS_PER_DOMAIN:
            seen[task.domain] += 1
            selected.append(task)
    print(f"{len(selected)} tasks from {len(seen)} domains")
    return selected


class GeneratorRun(FastDownwardRun):
    def __init__(self, exp, algo, task, env_prefix, requested_generator,
                 requested_timer):
        super().__init__(exp, algo, task)
        command, kwargs = self.commands["planner"]
        if not VALIDATE_PLANS:
            command = [part for part in command if part != "--validate"]
        self.commands["planner"] = (env_prefix + command, kwargs)
        self.set_property("requested_generator", requested_generator)
        self.set_property("requested_timer", requested_timer)


class GeneratorExperiment(FastDownwardExperiment):
    """Erlaubt Algorithmen, die sich nur in Umgebungsvariablen unterscheiden."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.env_prefix_by_algorithm = {}

    def add_generator_algorithm(self, name, requested_generator, requested_timer,
                                env_assignments, **kwargs):
        already_added = self._algorithms
        self._algorithms = OrderedDict()
        super().add_algorithm(name, REPO, REVISION, **kwargs)
        new_algorithm = self._algorithms[name]
        self._algorithms = already_added
        if name in self._algorithms:
            sys.exit(f"Algorithm names must be unique: {name}")
        self._algorithms[name] = new_algorithm

        env_prefix = ["env"]
        for var in ALL_GENERATOR_ENV_VARS:
            env_prefix += ["-u", var]
        self.env_prefix_by_algorithm[name] = (
            requested_generator, requested_timer, env_prefix + env_assignments)

    def _add_runs(self):
        tasks = self._get_tasks()
        for algo in self._algorithms.values():
            requested_generator, requested_timer, env_prefix = (
                self.env_prefix_by_algorithm[algo.name])
            for task in tasks:
                self.add_run(GeneratorRun(
                    self, algo, task, env_prefix, requested_generator,
                    requested_timer))


def get_parser():
    parser = Parser()
    parser.add_pattern(
        "generator_build_time_seconds",
        r"time for successor generation creation: ([\d.]+)s", type=float)
    parser.add_pattern(
        "generator_query_time_seconds",
        r"Time for successor generation: ([\d.]+)s", type=float)
    parser.add_pattern(
        "generator_number_of_queries",
        r"Successor generator calls: (\d+)", type=int)
    parser.add_pattern(
        "reported_generator",
        r"Successor generator method: (.+)", type=str)
    parser.add_pattern(
        "reported_timer",
        r"Successor generator timer: (.+)", type=str)
    parser.add_pattern(
        "reported_sorting",
        r"Successor generator sorting: (.+)", type=str)
    parser.add_pattern(
        "generator_peak_memory_kilobytes",
        r"peak memory difference for successor generator creation: (\d+) KB",
        type=int)
    return parser


OUT_OF_TIME_ERRORS = [
    "search-out-of-time",
    "search-out-of-memory-and-time",
    "search-plan-found-and-out-of-time",
    "search-plan-found-and-out-of-memory-and-time",
    "translate-out-of-time",
]

OUT_OF_MEMORY_ERRORS = [
    "search-out-of-memory",
    "search-out-of-memory-and-time",
    "search-plan-found-and-out-of-memory",
    "search-plan-found-and-out-of-memory-and-time",
    "translate-out-of-memory",
]


def compute_derived_values(run):
    error = run.get("error")
    run["out_of_time"] = int(error in OUT_OF_TIME_ERRORS)
    run["out_of_memory"] = int(error in OUT_OF_MEMORY_ERRORS)

    run["search_time_seconds"] = run.get("search_time")
    run["total_time_seconds"] = run.get("total_time")
    run["solved"] = run.get("coverage")
    run["expanded_states"] = run.get("expansions")
    run["evaluated_states"] = run.get("evaluations")
    run["generated_states"] = run.get("generated")
    run["solution_cost"] = run.get("cost")
    run["memory_kilobytes"] = run.get("memory")

    build_time = run.get("generator_build_time_seconds")
    query_time = run.get("generator_query_time_seconds")
    num_queries = run.get("generator_number_of_queries")
    search_time = run.get("search_time_seconds")
    total_time = run.get("total_time_seconds")

    if search_time is not None and query_time is not None:
        run["search_time_without_generator_seconds"] = search_time - query_time
    if total_time is not None and search_time is not None and build_time is not None:
        run["other_planner_time_seconds"] = total_time - search_time - build_time
    if query_time is not None and search_time:
        run["generator_share_of_search_time"] = query_time / search_time
    if query_time is not None and total_time:
        run["generator_share_of_total_time"] = query_time / total_time
    if build_time is not None and query_time is not None and total_time:
        run["generator_and_build_share_of_total_time"] = (
            (build_time + query_time) / total_time)
    if search_time is not None and total_time:
        run["search_share_of_total_time"] = search_time / total_time
    if query_time is not None and num_queries:
        run["time_per_query_microseconds"] = query_time / num_queries * 1_000_000

    if run.get("expanded_states") is not None:
        run["common_tasks"] = 1

    return run


def check_requested_setup_matches(run):
    for what in ["generator", "timer"]:
        reported = run.get(f"reported_{what}")
        if reported is None:
            continue
        requested = run[f"requested_{what}"]
        if reported.strip() != requested:
            tools.add_unexplained_error(
                run,
                f"requested {what} '{requested}', but planner used "
                f"'{reported.strip()}'")
    # Der ganze Test haengt daran, dass wirklich sortiert wurde.
    sorting = run.get("reported_sorting")
    if sorting is not None and sorting.strip() != "on":
        tools.add_unexplained_error(run, "sorting was not enabled")
    return True


def _time_attribute(name, digits=4):
    return Attribute(name, min_wins=True, function=arithmetic_mean, digits=digits)


def _share_attribute(name, digits=4):
    return Attribute(name, min_wins=False, function=arithmetic_mean, digits=digits)


COVERAGE_ATTRIBUTE = Attribute("solved", absolute=True, min_wins=False)
COMMON_TASKS_ATTRIBUTE = Attribute("common_tasks", min_wins=False)

ERROR_COUNT_ATTRIBUTES = [
    Attribute("out_of_time", absolute=True, min_wins=True),
    Attribute("out_of_memory", absolute=True, min_wins=True),
]

# Die drei Zustandszahlen stehen vorn: sie sind das Ergebnis dieses Tests.
MAIN_ATTRIBUTES = [
    "expanded_states",
    "evaluated_states",
    "generated_states",
    "generator_number_of_queries",
    "solution_cost",
    COVERAGE_ATTRIBUTE,
    COMMON_TASKS_ATTRIBUTE,
    *ERROR_COUNT_ATTRIBUTES,
    "error",
    _time_attribute("generator_build_time_seconds"),
    _time_attribute("generator_query_time_seconds"),
    _time_attribute("time_per_query_microseconds"),
    _time_attribute("search_time_without_generator_seconds"),
    _time_attribute("other_planner_time_seconds"),
    _time_attribute("search_time_seconds"),
    _time_attribute("total_time_seconds"),
    _share_attribute("generator_share_of_search_time"),
    _share_attribute("generator_share_of_total_time"),
    _share_attribute("generator_and_build_share_of_total_time"),
    _share_attribute("search_share_of_total_time"),
    "generator_peak_memory_kilobytes",
    "memory_kilobytes",
]

ATTRIBUTES = [
    "run_dir",
    "requested_generator",
    "reported_generator",
    "requested_timer",
    "reported_timer",
    "reported_sorting",
    *MAIN_ATTRIBUTES,
]

exp = GeneratorExperiment(environment=ENV)

for generator_id, generator_env, reported_generator in GENERATOR_METHODS:
    for config_id, config in SEARCH_CONFIGS:
        for timer_id, timer_value in TIMER_MODES:
            exp.add_generator_algorithm(
                f"{config_id}-{generator_id}-{timer_id}",
                reported_generator,
                timer_value,
                generator_env + [f"DOWNWARD_SG_TIMER={timer_value}",
                                 SORT_ASSIGNMENT],
                build_options=BUILD_OPTIONS,
                driver_options=DRIVER_OPTIONS,
                component_options=config,
            )

exp.add_suite(BENCHMARKS_DIR, select_tasks())

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
    name=f"{exp.name}-all",
    attributes=ATTRIBUTES,
    filter=[compute_derived_values, check_requested_setup_matches],
)

# Je Konfiguration und Timer eine Tabelle: vier Generatoren nebeneinander.
# Genau hier muessen die Expansionszahlen ueberall gleich sein.
for config_id, _ in SEARCH_CONFIGS:
    for timer_id, _ in TIMER_MODES:
        project.add_absolute_report(
            exp,
            name=f"{exp.name}-{config_id}-{timer_id}",
            attributes=MAIN_ATTRIBUTES,
            filter_algorithm=[
                f"{config_id}-{generator_id}-{timer_id}"
                for generator_id, _, _ in GENERATOR_METHODS
            ],
            filter=[compute_derived_values, check_requested_setup_matches],
        )

exp.run_steps()
