#! /usr/bin/env python

import itertools
import os
import shutil
import subprocess
import sys
from collections import OrderedDict

from downward.experiment import FastDownwardExperiment, FastDownwardRun
from lab import tools
from lab.parser import Parser
from lab.reports import Attribute, arithmetic_mean

import project

REPO = project.get_repo_base()
REVISION = "sg-marking"
SCP_LOGIN = "oglakc0000@login12.scicore.unibas.ch"
REMOTE_REPOS_DIR = "/infai/oglakc0000"


# lab builds the planner from this git revision, not from the working copy.
# A name that only exists as "origin/<name>" does not resolve, so fail here
# with a clear message instead of deep inside the build step.
def check_revision_exists(repo, revision):
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}"],
        capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(
            f"Revision '{revision}' not found in {repo}.\n"
            f"If it only exists on the remote, create a local branch first:\n"
            f"    git -C {repo} branch {revision} origin/{revision}")


check_revision_exists(REPO, REVISION)

# Every environment variable that can switch the successor generator.
# Listed here so we can delete ALL of them before setting the one we want.
ALL_GENERATOR_ENV_VARS = [
    "DOWNWARD_SG_NAIVE",
    "DOWNWARD_SG_WATCHED_LITERALS",
    "DOWNWARD_SG_MARKING",
    "DOWNWARD_SG_TIMER",
]

# One entry per generator we compare:
# (short id used in file/algorithm names, env vars to set, name printed by the planner)
# "naive" is listed first on purpose: scatter plots put the first algorithm of
# a pair on the x-axis (bottom), and every scatter plot below compares the
# other three generators against naive, so naive always ends up on the
# x-axis (bottom) and the other generator on the y-axis.
GENERATOR_METHODS = [
    ("naive", ["DOWNWARD_SG_NAIVE=1"], "naive"),
    ("match_tree", [], "match tree"),
    ("watched_literals", ["DOWNWARD_SG_WATCHED_LITERALS=1"], "watched literals"),
    ("marking", ["DOWNWARD_SG_MARKING=1"], "marking"),
]

# One entry per search setting we test every generator with.
SEARCH_CONFIGS = [
    ("astar-blind", ["--search", "astar(blind())"]),
    ("greedy-ff", ["--search", "eager_greedy([ff()])"]),
]

# How the time inside generate_applicable_ops is measured. This is a third
# dimension next to generator and search config, so the cost of the
# measurement itself becomes a measured number instead of an assumption.
#   off        no measurement at all -> honest search and total time
#   cpu        utils::Timer, i.e. clock_gettime(CLOCK_PROCESS_CPUTIME_ID),
#              which is what the planner used so far
#   monotonic  clock_gettime(CLOCK_MONOTONIC), about ten times cheaper and
#              not degraded to millisecond granularity by RLIMIT_CPU
# Trim this list to shrink the experiment; every entry multiplies the runs.
TIMER_MODES = [
    ("timer_off", "off"),
    ("timer_cpu", "cpu"),
    ("timer_monotonic", "monotonic"),
]

BUILD_OPTIONS = ["-j4"]

# infai_2 nodes have 3872 MiB per core; stay below that so slurm does not
# kill the job before the planner hits its own limit.
MEMORY_LIMIT = "3584M"

# Modules to load on the compute node. lab 8.10 ships an EMPTY default setup
# for BaselSlurmEnvironment, so without this the node has no usable
# GCC/Python/CMake and the runs fail.
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
    SUITE = project.SUITE_OPTIMAL_STRIPS
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


# lab always passes --validate. Without VAL on the PATH the driver aborts with
# "driver-input-error" AFTER the search, so every solved run is flagged as an
# unexplained error and real errors drown in the noise. Correctness of the
# generators is covered by misc/tests/check_successor_generator_correctness.py
# and by the cost check below, so dropping validation is safe.
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
        # What we asked for. Compared later against what the planner reports
        # having used (see check_requested_setup_matches).
        self.set_property("requested_generator", requested_generator)
        self.set_property("requested_timer", requested_timer)


class GeneratorExperiment(FastDownwardExperiment):
    """A FastDownwardExperiment that can add several algorithms which only
    differ by an environment variable (lab would normally reject this,
    since it treats same revision + same driver + same search config as
    "the same algorithm")."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.env_prefix_by_algorithm = {}

    def add_generator_algorithm(self, name, requested_generator, requested_timer,
                                env_assignments, **kwargs):
        # Hide the already-added algorithms so lab's "is this a duplicate?"
        # check has nothing to compare against, then restore them and do
        # our own duplicate-name check by hand.
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
    # The memory the data structure itself costs. This is the price the match
    # tree pays for being fast, so the comparison is incomplete without it.
    parser.add_pattern(
        "generator_peak_memory_kilobytes",
        r"peak memory difference for successor generator creation: (\d+) KB",
        type=int,
    )
    return parser


# Fast Downward's exit codes, as named by lab (downward/outcomes.py). Listed
# explicitly instead of matching substrings: "search-out-of-memory-and-time"
# does NOT contain "out-of-time", so a substring test would miss exactly the
# case where both limits were hit.
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
    run["solved"] = run.get("coverage")
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

    return run


def check_requested_setup_matches(run):
    """Guard against a silently wrong run.

    If an env var does not arrive, the planner falls back to the match tree
    and to the cpu timer without saying anything, and the whole comparison
    would be worthless without it being visible anywhere.
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

# Coverage must be summed over ALL tasks (absolute=True) and more is better.
# Without this it is aggregated over commonly solved tasks only, where it is
# equal by construction, and lower would be reported as better.
COVERAGE_ATTRIBUTE = Attribute("solved", absolute=True, min_wins=False)

# Number of tasks the times and state counts are aggregated over. Not
# absolute, so it goes through the same commonly-solved filter as those
# attributes and is the same in every column.
COMMON_TASKS_ATTRIBUTE = Attribute("common_tasks", min_wins=False)

# Counted over ALL tasks as well, otherwise a failure would be dropped from
# the table precisely because it is a failure.
ERROR_COUNT_ATTRIBUTES = [
    Attribute("out_of_time", absolute=True, min_wins=True),
    Attribute("out_of_memory", absolute=True, min_wins=True),
]

COUNT_ATTRIBUTES = [
    COVERAGE_ATTRIBUTE,
    COMMON_TASKS_ATTRIBUTE,
    *ERROR_COUNT_ATTRIBUTES,
    "solution_cost",
    "expanded_states",
    "evaluated_states",
    "generated_states",
    "generator_number_of_queries",
    "generator_peak_memory_kilobytes",
    "memory_kilobytes",
]

# lab's own scores, computed from the unrenamed attributes. They map a runtime
# to [0, 1] on a log scale and, unlike a mean over commonly solved tasks, they
# also account for the tasks a generator failed to solve.
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
    *COUNT_ATTRIBUTES,
    *TIME_ATTRIBUTES,
    *SHARE_ATTRIBUTES,
    *SCORE_ATTRIBUTES,
]

# The metrics the thesis actually compares, in reading order. The report built
# from these is the one that goes into the evaluation chapter; the full report
# above keeps everything else for digging into single results.
# All four time attributes are aggregated with the arithmetic mean, because
# they are additive: generator build + generator generation + rest = search.
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


for config_id, config in SEARCH_CONFIGS:
    for method_id, generator_assignments, requested_generator in GENERATOR_METHODS:
        for timer_id, requested_timer in TIMER_MODES:
            exp.add_generator_algorithm(
                algorithm_name(config_id, method_id, timer_id),
                requested_generator,
                requested_timer,
                generator_assignments + [f"DOWNWARD_SG_TIMER={requested_timer}"],
                component_options=config,
                build_options=BUILD_OPTIONS,
                driver_options=DRIVER_OPTIONS,
            )

METHOD_IDS = [method_id for method_id, _, _ in GENERATOR_METHODS]
TIMER_IDS = [timer_id for timer_id, _ in TIMER_MODES]
CONFIG_IDS = [config_id for config_id, _ in SEARCH_CONFIGS]

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

# The generator comparison: four generators side by side, same timer mode, and
# ONE search config per table.
#
# The search config must not be mixed into one table. For every attribute with
# absolute=False (times, expansions, evaluations) lab aggregates over the tasks
# that ALL columns of that table solved. With both configs in one table, a task
# that astar-blind cannot solve would also be dropped from the greedy-ff
# comparison, and the other way round. One config per table means "solved by
# all four generators" really is the set being compared.
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

# The timer comparison: the same generator measured three ways, again one
# search config per table. The difference between the columns is what the
# measurement itself costs.
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

# All four generators return the same set of applicable operators, so under
# astar(blind()) they must all find plans of the same cost. Different orderings
# may change expansions and which optimal plan is found, but never the cost.
# A differing cost here means a generator drops or invents operators.
project.add_absolute_report(
    exp,
    name=f"{exp.name}-cost-check-astar-blind",
    attributes=[COVERAGE_ATTRIBUTE, "solution_cost", "expanded_states", "generated_states"],
    filter=[compute_derived_values, project.OptimalityCheckFilter().check_costs],
    filter_algorithm=[
        algorithm_name("astar-blind", method_id, timer_id)
        for method_id in METHOD_IDS
        for timer_id in TIMER_IDS
    ],
)

# Scatter plots only for astar-blind: with three timer modes the full cross
# product would be several hundred plots, and blind search is the setting where
# successor generation carries the most weight.
SCATTER_CONFIG = "astar-blind"

# Generator against generator, all measured without a timer: the honest runtime
# comparison of the four methods.
generator_pairs = [
    (algorithm_name(SCATTER_CONFIG, first, "timer_off"),
     algorithm_name(SCATTER_CONFIG, second, "timer_off"))
    for first, second in itertools.combinations(METHOD_IDS, 2)
]
project.add_scatter_plot_reports(
    exp, generator_pairs, ["total_time_seconds", "search_time_seconds"],
    filter=[compute_derived_values])

# Generator against generator on the measured generator time itself, using the
# cheap clock.
generator_pairs_monotonic = [
    (algorithm_name(SCATTER_CONFIG, first, "timer_monotonic"),
     algorithm_name(SCATTER_CONFIG, second, "timer_monotonic"))
    for first, second in itertools.combinations(METHOD_IDS, 2)
]
project.add_scatter_plot_reports(
    exp, generator_pairs_monotonic, ["generator_query_time_seconds"],
    filter=[compute_derived_values])

# The same generator against itself under two timer modes. Every point off the
# diagonal is what the measurement itself costs.
timer_pairs = [
    (algorithm_name(SCATTER_CONFIG, method_id, first),
     algorithm_name(SCATTER_CONFIG, method_id, second))
    for method_id in METHOD_IDS
    for first, second in itertools.combinations(TIMER_IDS, 2)
]
project.add_scatter_plot_reports(
    exp, timer_pairs, ["total_time_seconds", "search_time_seconds"],
    filter=[compute_derived_values])

if not project.REMOTE:
    project.add_scp_step(exp, SCP_LOGIN, REMOTE_REPOS_DIR)

exp.run_steps()
