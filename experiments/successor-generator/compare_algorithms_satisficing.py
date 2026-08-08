#! /usr/bin/env python

"""Satisficing-Experiment mit zwei gekreuzten Achsen.

                    ff        cg
    eager_greedy    x         x
    lazy_greedy     x         x

Zeilenvergleich -> nur der Suchalgorithmus wechselt, Spaltenvergleich -> nur
die Heuristik. Im ersten Experiment wechselten beide gleichzeitig.

Der Zeilenvergleich ist der Punkt: eager wertet die Heuristik fuer jeden
erzeugten Nachfolger sofort aus, lazy erst beim Herausnehmen aus der Open
List. Bei lazy laeuft sie also seltener und der Anteil der
Nachfolgegenerierung steigt, obwohl der Generator dieselbe Arbeit macht.

Dazu astar(blind()) als obere Schranke und lama-first als Wettbewerbsplaner.
lama-first gehoert nicht zu den Achsen: zwei Heuristiken, preferred
operators, Kostentransformation - und die Landmark-Heuristik baut einen
zweiten Successor Generator, den die Umgebungsvariable mitumschaltet.
"""

import itertools
import os
import shutil
import subprocess
import sys
from collections import OrderedDict

from downward.experiment import FastDownwardExperiment, FastDownwardRun
from downward.reports.scatter import ScatterPlotReport
from lab import tools
from lab.parser import Parser
from lab.reports import Attribute, arithmetic_mean

import project

REPO = project.get_repo_base()
REVISION = "successor_generators"
SCP_LOGIN = "oglakc0000@login12.scicore.unibas.ch"
REMOTE_REPOS_DIR = "/infai/oglakc0000"


def check_revision_exists(repo, revision):
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet",
         f"{revision}^{{commit}}"],
        capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(
            f"Revision '{revision}' not found in {repo}.\n"
            f"If it only exists on the remote, create a local branch first:\n"
            f"    git -C {repo} branch {revision} origin/{revision}")


check_revision_exists(REPO, REVISION)

ALL_GENERATOR_ENV_VARS = [
    "DOWNWARD_SG_NAIVE",
    "DOWNWARD_SG_WATCHED_LITERALS",
    "DOWNWARD_SG_MARKING",
    "DOWNWARD_SG_TIMER",
]

# naive first so it lands on the x-axis of every scatter plot.
GENERATOR_METHODS = [
    ("naive", ["DOWNWARD_SG_NAIVE=1"], "naive"),
    ("match_tree", [], "match tree"),
    ("watched_literals", ["DOWNWARD_SG_WATCHED_LITERALS=1"], "watched literals"),
    ("marking", ["DOWNWARD_SG_MARKING=1"], "marking"),
]

# Third entry per row is extra driver options: lab builds the command as
# driver_options + input_files + component_options, so --alias has to stand
# before the pddl files and cannot go into component_options.
SEARCH_CONFIGS = [
    ("astar-blind", ["--search", "astar(blind())"], []),
    ("eager-ff", ["--search", "eager_greedy([ff()])"], []),
    ("eager-cg", ["--search", "eager_greedy([cg()])"], []),
    ("lazy-ff", ["--search", "lazy_greedy([ff()])"], []),
    ("lazy-cg", ["--search", "lazy_greedy([cg()])"], []),
    ("lama-first", [], ["--alias", "lama-first"]),
]

# Rows of the grid: same heuristic, eager against lazy.
ALGORITHM_PAIRS = [
    ("eager-ff", "lazy-ff"),
    ("eager-cg", "lazy-cg"),
]

# Columns of the grid: same search algorithm, ff against cg.
HEURISTIC_PAIRS = [
    ("eager-ff", "eager-cg"),
    ("lazy-ff", "lazy-cg"),
]

# off gives honest times, monotonic measures the generator cheaply, cpu shows
# what the expensive clock costs.
TIMER_MODES = [
    ("timer_off", "off"),
    ("timer_monotonic", "monotonic"),
    ("timer_cpu", "cpu"),
]

BUILD_OPTIONS = ["-j4"]
MEMORY_LIMIT = "3584M"

CLUSTER_SETUP = "\n".join([
    "module purge",
    "module -q load GCC/13.2.0",
    "module -q load Python/3.11.5-GCCcore-13.2.0",
    "module -q load CMake/3.27.6-GCCcore-13.2.0",
])

if project.REMOTE:
    BENCHMARKS_DIR = os.environ.get("DOWNWARD_BENCHMARKS")
    if not BENCHMARKS_DIR:
        sys.exit("Set DOWNWARD_BENCHMARKS to the downward-benchmarks checkout.")
    SUITE = project.SUITE_SATISFICING
    ENV = project.BaselSlurmEnvironment(
        partition="infai_2",
        qos="infai",
        memory_per_cpu="3872M",
        email="d.oglakcioglu@unibas.ch",
        setup=CLUSTER_SETUP,
    )
    TIME_LIMIT = "5m"
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


class GeneratorRun(FastDownwardRun):
    """A run that runs the planner with a generator env var already set."""

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
    """Lets several algorithms differ only by an environment variable."""

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
        r"time for successor generation creation: ([\d.]+)s",
        type=float,
    )
    parser.add_pattern(
        "generator_query_time_seconds",
        r"Time for successor generation: ([\d.]+)s",
        type=float,
    )
    parser.add_pattern(
        "generator_number_of_queries",
        r"Successor generator calls: (\d+)",
        type=int,
    )
    parser.add_pattern(
        "reported_generator",
        r"Successor generator method: (.+)",
        type=str,
    )
    parser.add_pattern(
        "reported_timer",
        r"Successor generator timer: (.+)",
        type=str,
    )
    parser.add_pattern(
        "generator_peak_memory_kilobytes",
        r"peak memory difference for successor generator creation: (\d+) KB",
        type=int,
    )
    # Task size, for grouping tasks and as x-axis of the scatter plots.
    parser.add_pattern("task_variables", r"Task variables: (\d+)", type=int)
    parser.add_pattern("task_facts", r"Task facts: (\d+)", type=int)
    parser.add_pattern("task_operators", r"Task operators: (\d+)", type=int)
    parser.add_pattern("task_axioms", r"Task axioms: (\d+)", type=int)
    parser.add_pattern("task_goals", r"Task goals: (\d+)", type=int)
    parser.add_pattern(
        "task_preconditions", r"Task preconditions: (\d+)", type=int)
    parser.add_pattern(
        "task_max_preconditions",
        r"Task max preconditions per operator: (\d+)", type=int)
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

    run["translator_time_seconds"] = run.get("translator_time_done")
    run["search_time_seconds"] = run.get("search_time")
    run["total_time_seconds"] = run.get("total_time")
    run["expanded_states"] = run.get("expansions")
    run["evaluated_states"] = run.get("evaluations")
    run["generated_states"] = run.get("generated")
    run["memory_kilobytes"] = run.get("memory")
    run["solution_cost"] = run.get("cost")

    build_time = run.get("generator_build_time_seconds")
    query_time = run.get("generator_query_time_seconds")
    num_queries = run.get("generator_number_of_queries")
    expansions = run.get("expanded_states")
    search_time = run.get("search_time_seconds")
    total_time = run.get("total_time_seconds")
    translator_time = run.get("translator_time_seconds")

    if search_time is not None and query_time is not None:
        run["search_time_without_generator_seconds"] = search_time - query_time
    if total_time is not None and search_time is not None and build_time is not None:
        run["other_planner_time_seconds"] = total_time - search_time - build_time
    if translator_time is not None and total_time is not None:
        run["total_time_with_translator_seconds"] = translator_time + total_time

    if query_time is not None and search_time:
        run["generator_share_of_search_time"] = query_time / search_time
    if query_time is not None and total_time:
        run["generator_share_of_total_time"] = query_time / total_time
    if build_time is not None and query_time is not None and total_time:
        run["generator_and_build_share_of_total_time"] = (build_time + query_time) / total_time
    if search_time is not None and total_time:
        run["search_share_of_total_time"] = search_time / total_time

    if query_time is not None and num_queries:
        run["time_per_query_microseconds"] = query_time / num_queries * 1_000_000
    if num_queries is not None and expansions:
        run["queries_per_expansion"] = num_queries / expansions

    # One per run, so summing counts tasks.
    if expansions is not None:
        run["common_tasks"] = 1

    num_operators = run.get("task_operators")
    num_preconditions = run.get("task_preconditions")
    if num_operators:
        run["preconditions_per_operator"] = num_preconditions / num_operators
        # Bucket by order of magnitude, so tables can be split by task size
        # without picking arbitrary cut-offs per domain.
        for upper, name in [(100, "1 up to 100"),
                            (1_000, "2 100 to 1k"),
                            (10_000, "3 1k to 10k"),
                            (100_000, "4 10k to 100k")]:
            if num_operators < upper:
                run["operator_count_class"] = name
                break
        else:
            run["operator_count_class"] = "5 over 100k"

    return run


def check_requested_setup_matches(run):
    """Guard against a silently wrong run.

    If an env var does not arrive, the planner falls back to the match tree
    and to the cpu timer without saying anything.
    """
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
    return True


def _time_attribute(name, digits=4):
    return Attribute(name, min_wins=True, function=arithmetic_mean, digits=digits)


def _share_attribute(name, digits=4):
    return Attribute(name, min_wins=False, function=arithmetic_mean, digits=digits)


TIME_ATTRIBUTES = [
    _time_attribute("translator_time_seconds"),
    _time_attribute("generator_build_time_seconds"),
    _time_attribute("generator_query_time_seconds"),
    _time_attribute("time_per_query_microseconds"),
    _time_attribute("search_time_without_generator_seconds"),
    _time_attribute("other_planner_time_seconds"),
    _time_attribute("search_time_seconds"),
    _time_attribute("total_time_seconds"),
    _time_attribute("total_time_with_translator_seconds"),
]

SHARE_ATTRIBUTES = [
    _share_attribute("generator_share_of_search_time"),
    _share_attribute("generator_share_of_total_time"),
    _share_attribute("generator_and_build_share_of_total_time"),
    _share_attribute("search_share_of_total_time"),
    _share_attribute("queries_per_expansion"),
]

COVERAGE_ATTRIBUTE = Attribute("coverage", absolute=True, min_wins=False)

# Not absolute, so it goes through the same commonly-solved filter as the
# times and is identical in every column.
COMMON_TASKS_ATTRIBUTE = Attribute("common_tasks", min_wins=False)

ERROR_COUNT_ATTRIBUTES = [
    Attribute("out_of_time", absolute=True, min_wins=True),
    Attribute("out_of_memory", absolute=True, min_wins=True),
]

COUNT_ATTRIBUTES = [
    COVERAGE_ATTRIBUTE,
    COMMON_TASKS_ATTRIBUTE,
    *ERROR_COUNT_ATTRIBUTES,
    "solution_cost",
    "plan_length",
    "expanded_states",
    "evaluated_states",
    "generated_states",
    "dead_ends",
    "reopened",
    "generator_number_of_queries",
    "generator_peak_memory_kilobytes",
    "memory_kilobytes",
]

# Identical in every column for a given task, so these never distinguish
# generators - they classify tasks.
TASK_SIZE_ATTRIBUTES = [
    Attribute("task_variables", absolute=True, min_wins=None),
    Attribute("task_facts", absolute=True, min_wins=None),
    Attribute("task_operators", absolute=True, min_wins=None),
    Attribute("task_axioms", absolute=True, min_wins=None),
    Attribute("task_goals", absolute=True, min_wins=None),
    Attribute("task_preconditions", absolute=True, min_wins=None),
    Attribute("task_max_preconditions", absolute=True, min_wins=None),
    Attribute("preconditions_per_operator", absolute=True, min_wins=None,
              function=arithmetic_mean, digits=2),
]

SCORE_ATTRIBUTES = [
    Attribute("score_search_time", absolute=True, min_wins=False, digits=4),
    Attribute("score_total_time", absolute=True, min_wins=False, digits=4),
    Attribute("score_memory", absolute=True, min_wins=False, digits=4),
]

ATTRIBUTES = [
    "error",
    "run_dir",
    "requested_generator",
    "reported_generator",
    "requested_timer",
    "reported_timer",
    "operator_count_class",
    *COUNT_ATTRIBUTES,
    *TASK_SIZE_ATTRIBUTES,
    *TIME_ATTRIBUTES,
    *SHARE_ATTRIBUTES,
    *SCORE_ATTRIBUTES,
]

MAIN_ATTRIBUTES = [
    "error",
    *ERROR_COUNT_ATTRIBUTES,
    COVERAGE_ATTRIBUTE,
    COMMON_TASKS_ATTRIBUTE,
    "evaluated_states",
    "expanded_states",
    "generated_states",
    "generator_number_of_queries",
    _time_attribute("generator_build_time_seconds"),
    _time_attribute("generator_query_time_seconds"),
    _share_attribute("generator_share_of_search_time"),
    _time_attribute("search_time_seconds"),
    _time_attribute("total_time_seconds"),
]

exp = GeneratorExperiment(environment=ENV)


def algorithm_name(config_id, method_id, timer_id):
    return f"{config_id}-{method_id}-{timer_id}"


for config_id, config, extra_driver_options in SEARCH_CONFIGS:
    for method_id, generator_assignments, requested_generator in GENERATOR_METHODS:
        for timer_id, requested_timer in TIMER_MODES:
            exp.add_generator_algorithm(
                algorithm_name(config_id, method_id, timer_id),
                requested_generator,
                requested_timer,
                generator_assignments + [f"DOWNWARD_SG_TIMER={requested_timer}"],
                component_options=config,
                build_options=BUILD_OPTIONS,
                driver_options=DRIVER_OPTIONS + extra_driver_options,
            )

METHOD_IDS = [method_id for method_id, _, _ in GENERATOR_METHODS]
TIMER_IDS = [timer_id for timer_id, _ in TIMER_MODES]
CONFIG_IDS = [config_id for config_id, _, _ in SEARCH_CONFIGS]

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

FILTERS = [compute_derived_values, check_requested_setup_matches]

project.add_absolute_report(
    exp, name=f"{exp.name}-main", attributes=MAIN_ATTRIBUTES, filter=FILTERS)

project.add_absolute_report(
    exp, name=f"{exp.name}-all", attributes=ATTRIBUTES, filter=FILTERS)

# Four generators side by side, one configuration per table: mixing them
# would shrink every column to what astar-blind solves.
for timer_id in TIMER_IDS:
    for config_id in CONFIG_IDS:
        project.add_absolute_report(
            exp,
            name=f"{exp.name}-generators-{config_id}-{timer_id}",
            attributes=MAIN_ATTRIBUTES,
            filter=FILTERS,
            filter_algorithm=[
                algorithm_name(config_id, method_id, timer_id)
                for method_id in METHOD_IDS
            ],
        )

# Rows: same heuristic, eager against lazy. The point of the experiment.
for eager_config, lazy_config in ALGORITHM_PAIRS:
    for method_id in METHOD_IDS:
        for timer_id in TIMER_IDS:
            project.add_absolute_report(
                exp,
                name=f"{exp.name}-eagerlazy-{eager_config}-{method_id}-{timer_id}",
                attributes=MAIN_ATTRIBUTES,
                filter=FILTERS,
                filter_algorithm=[
                    algorithm_name(eager_config, method_id, timer_id),
                    algorithm_name(lazy_config, method_id, timer_id),
                ],
            )

# Columns: same search algorithm, ff against cg.
for ff_config, cg_config in HEURISTIC_PAIRS:
    for method_id in METHOD_IDS:
        for timer_id in TIMER_IDS:
            project.add_absolute_report(
                exp,
                name=f"{exp.name}-heuristics-{ff_config}-{method_id}-{timer_id}",
                attributes=MAIN_ATTRIBUTES,
                filter=FILTERS,
                filter_algorithm=[
                    algorithm_name(ff_config, method_id, timer_id),
                    algorithm_name(cg_config, method_id, timer_id),
                ],
            )

# All six configurations at once. The commonly-solved filter cuts this down
# to what astar-blind manages, so read it as a spread, not as the numbers.
for method_id in METHOD_IDS:
    for timer_id in TIMER_IDS:
        project.add_absolute_report(
            exp,
            name=f"{exp.name}-allconfigs-{method_id}-{timer_id}",
            attributes=MAIN_ATTRIBUTES,
            filter=FILTERS,
            filter_algorithm=[
                algorithm_name(config_id, method_id, timer_id)
                for config_id in CONFIG_IDS
            ],
        )

# The three clocks: the difference between the columns is the measurement.
for method_id in METHOD_IDS:
    for config_id in CONFIG_IDS:
        project.add_absolute_report(
            exp,
            name=f"{exp.name}-timers-{config_id}-{method_id}",
            attributes=MAIN_ATTRIBUTES,
            filter=FILTERS,
            filter_algorithm=[
                algorithm_name(config_id, method_id, timer_id)
                for timer_id in TIMER_IDS
            ],
        )

# Split by task size: naive should fall behind as the operator count grows,
# since its cost is linear in it.
OPERATOR_COUNT_CLASSES = [
    "1 up to 100", "2 100 to 1k", "3 1k to 10k", "4 10k to 100k",
    "5 over 100k",
]

# Shared with the first experiment, so these stay comparable.
SIZE_REPORT_CONFIG = "eager-ff"
SIZE_REPORT_TIMER = "timer_monotonic"


def keep_operator_count_class(wanted):
    def keep(run):
        return run.get("operator_count_class") == wanted
    return keep


for size_class in OPERATOR_COUNT_CLASSES:
    slug = size_class.split(" ", 1)[0]
    project.add_absolute_report(
        exp,
        name=f"{exp.name}-size{slug}-{SIZE_REPORT_CONFIG}",
        attributes=MAIN_ATTRIBUTES,
        filter=FILTERS + [keep_operator_count_class(size_class)],
        filter_algorithm=[
            algorithm_name(SIZE_REPORT_CONFIG, method_id, SIZE_REPORT_TIMER)
            for method_id in METHOD_IDS
        ],
    )

# Scatter plots: one point per task, only where both algorithms solved.
SCATTER_CONFIG = "eager-ff"
SCATTER_TIMER = "timer_monotonic"

generator_pairs = [
    (algorithm_name(SCATTER_CONFIG, first, SCATTER_TIMER),
     algorithm_name(SCATTER_CONFIG, second, SCATTER_TIMER))
    for first, second in itertools.combinations(METHOD_IDS, 2)
]
project.add_scatter_plot_reports(
    exp, generator_pairs,
    ["total_time_seconds", "search_time_seconds",
     "generator_query_time_seconds", "time_per_query_microseconds",
     "expanded_states"],
    filter=[compute_derived_values])

# Same plots coloured by operator count instead of domain: shows whether the
# generators separate with task size.
def colour_by_operator_count(run1, run2):
    return run1.get("operator_count_class", "unknown")


for first, second in itertools.combinations(METHOD_IDS, 2):
    algo1 = algorithm_name(SCATTER_CONFIG, first, SCATTER_TIMER)
    algo2 = algorithm_name(SCATTER_CONFIG, second, SCATTER_TIMER)
    for attribute in ["generator_query_time_seconds",
                      "time_per_query_microseconds"]:
        exp.add_report(
            ScatterPlotReport(
                relative=False,
                get_category=colour_by_operator_count,
                attributes=[attribute],
                filter_algorithm=[algo1, algo2],
                filter=[compute_derived_values],
                format="png",
            ),
            name=f"{exp.name}-bysize-{first}-{second}-{attribute}",
        )

# eager against lazy, heuristic fixed: every point off the diagonal is the
# effect of the search algorithm.
eager_lazy_pairs = [
    (algorithm_name(eager_config, method_id, SCATTER_TIMER),
     algorithm_name(lazy_config, method_id, SCATTER_TIMER))
    for method_id in METHOD_IDS
    for eager_config, lazy_config in ALGORITHM_PAIRS
]
project.add_scatter_plot_reports(
    exp, eager_lazy_pairs,
    ["generator_share_of_search_time", "search_time_seconds",
     "generator_query_time_seconds"],
    filter=[compute_derived_values])

# ff against cg, search algorithm fixed.
heuristic_pairs = [
    (algorithm_name(ff_config, method_id, SCATTER_TIMER),
     algorithm_name(cg_config, method_id, SCATTER_TIMER))
    for method_id in METHOD_IDS
    for ff_config, cg_config in HEURISTIC_PAIRS
]
project.add_scatter_plot_reports(
    exp, heuristic_pairs,
    ["generator_share_of_search_time", "search_time_seconds"],
    filter=[compute_derived_values])

if not project.REMOTE:
    project.add_scp_step(exp, SCP_LOGIN, REMOTE_REPOS_DIR)

exp.run_steps()
