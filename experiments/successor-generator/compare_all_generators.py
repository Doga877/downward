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
REMOTE_REPOS_DIR = "/infai/oglakc0000"

# Every environment variable that can switch the successor generator.
# Listed here so we can delete ALL of them before setting the one we want.
ALL_GENERATOR_ENV_VARS = [
    "DOWNWARD_SG_NAIVE",
    "DOWNWARD_SG_WATCHED_LITERALS",
    "DOWNWARD_SG_MARKING",
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

DOMAINS = [
    "airport", "blocks", "depot", "driverlog", "elevators-opt08-strips",
    "freecell", "grid", "gripper", "logistics00", "miconic", "movie",
    "mprime", "nomystery-opt11-strips", "openstacks-opt08-strips",
    "parcprinter-08-strips", "pegsol-08-strips", "pipesworld-notankage",
    "psr-small", "rovers", "satellite", "scanalyzer-08-strips",
    "sokoban-opt08-strips", "tpp", "transport-opt08-strips", "trucks-strips",
    "visitall-opt11-strips", "woodworking-opt08-strips", "zenotravel",
]

TASKS_PER_DOMAIN = 6

BUILD_OPTIONS = ["-j4"]


def select_tasks(benchmarks_dir, domains, count):
    selected = []
    for domain in domains:
        for task in suites.build_suite(benchmarks_dir, [domain])[:count]:
            selected.append(f"{task.domain}:{task.problem}")
    return selected


if project.REMOTE:
    BENCHMARKS_DIR = os.environ["DOWNWARD_BENCHMARKS"]
    SUITE = select_tasks(BENCHMARKS_DIR, DOMAINS, TASKS_PER_DOMAIN)
    ENV = project.BaselSlurmEnvironment(email="d.oglakcioglu@unibas.ch")
    TIME_LIMIT = "5m"
else:
    BENCHMARKS_DIR = REPO / "misc" / "tests" / "benchmarks"
    SUITE = ["gripper", "miconic", "philosophers"]
    ENV = project.LocalEnvironment(processes=2)
    TIME_LIMIT = "60s"

DRIVER_OPTIONS = ["--overall-time-limit", TIME_LIMIT, "--search-memory-limit", "3500M"]


class GeneratorRun(FastDownwardRun):
    """A run that runs the planner with a generator env var already set."""

    def __init__(self, exp, algo, task, env_prefix, requested_generator):
        super().__init__(exp, algo, task)
        command, kwargs = self.commands["planner"]
        self.commands["planner"] = (env_prefix + command, kwargs)
        # The generator we asked for. Compared later against what the
        # planner actually reports having used (see check_generator_matches).
        self.set_property("requested_generator", requested_generator)


class GeneratorExperiment(FastDownwardExperiment):
    """A FastDownwardExperiment that can add several algorithms which only
    differ by an environment variable (lab would normally reject this,
    since it treats same revision + same driver + same search config as
    "the same algorithm")."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.env_prefix_by_algorithm = {}

    def add_generator_algorithm(self, name, requested_generator, env_assignments, **kwargs):
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
        self.env_prefix_by_algorithm[name] = (requested_generator, env_prefix + env_assignments)

    def _add_runs(self):
        tasks = self._get_tasks()
        for algo in self._algorithms.values():
            requested_generator, env_prefix = self.env_prefix_by_algorithm[algo.name]
            for task in tasks:
                self.add_run(GeneratorRun(self, algo, task, env_prefix, requested_generator))


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
    return parser


def compute_derived_values(run):
    run["translator_time_seconds"] = run.get("translator_time_done")
    run["search_time_seconds"] = run.get("search_time")
    run["total_time_seconds"] = run.get("total_time")
    run["solved"] = run.get("coverage")
    run["expanded_states"] = run.get("expansions")
    run["evaluated_states"] = run.get("evaluations")
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

    return run


def check_generator_matches(run):
    reported = run.get("reported_generator")
    if reported is not None:
        requested = run["requested_generator"]
        if reported.strip() != requested:
            tools.add_unexplained_error(
                run, f"requested '{requested}', but planner used '{reported.strip()}'"
            )
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

COUNT_ATTRIBUTES = [
    "solved",
    "solution_cost",
    "expanded_states",
    "evaluated_states",
    "generator_number_of_queries",
    "memory_kilobytes",
]

ATTRIBUTES = [
    "error",
    "run_dir",
    "requested_generator",
    "reported_generator",
    *COUNT_ATTRIBUTES,
    *TIME_ATTRIBUTES,
    *SHARE_ATTRIBUTES,
]

SCATTER_ATTRIBUTES = [
    "generator_query_time_seconds",
    "time_per_query_microseconds",
    "total_time_seconds",
]


exp = GeneratorExperiment(environment=ENV)

# algorithm_names_by_config["astar-blind"] == ["astar-blind-match_tree", ...]
algorithm_names_by_config = {}
scatter_plot_pairs = []
for config_id, config in SEARCH_CONFIGS:
    algorithm_names = []
    for method_id, env_assignments, requested_generator in GENERATOR_METHODS:
        algorithm_name = f"{config_id}-{method_id}"
        exp.add_generator_algorithm(
            algorithm_name,
            requested_generator,
            env_assignments,
            component_options=config,
            build_options=BUILD_OPTIONS,
            driver_options=DRIVER_OPTIONS,
        )
        algorithm_names.append(algorithm_name)
    algorithm_names_by_config[config_id] = algorithm_names
    scatter_plot_pairs += list(itertools.combinations(algorithm_names, 2))

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
    name=f"{exp.name}-all",
    attributes=ATTRIBUTES,
    filter=[compute_derived_values, check_generator_matches],
)

# One table per pair of generators (both search configs together). If one
# generator crashes everywhere, only its own pair-reports go empty, not the
# report with all four generators.
method_ids = [method_id for method_id, _, _ in GENERATOR_METHODS]
for first_method, second_method in itertools.combinations(method_ids, 2):
    project.add_absolute_report(
        exp,
        name=f"{exp.name}-{first_method}-vs-{second_method}",
        attributes=ATTRIBUTES,
        filter=[compute_derived_values, check_generator_matches],
        filter_algorithm=[
            f"{config_id}-{method}"
            for config_id, _ in SEARCH_CONFIGS
            for method in (first_method, second_method)
        ],
    )

project.add_scatter_plot_reports(
    exp, scatter_plot_pairs, SCATTER_ATTRIBUTES, filter=[compute_derived_values]
)

if not project.REMOTE:
    project.add_scp_step(exp, SCP_LOGIN, REMOTE_REPOS_DIR)

exp.run_steps()
