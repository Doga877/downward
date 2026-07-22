#! /usr/bin/env python

import os

from lab.parser import Parser
from lab.reports import Attribute, arithmetic_mean

import project

REPO = project.get_repo_base()
BENCHMARKS_DIR = os.environ["DOWNWARD_BENCHMARKS"]
SCP_LOGIN = "oglakc0000@login.infai.org"
REMOTE_REPOS_DIR = "/infai/oglakc0000/projects"

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
REV_NICKS = [("main", "")]


def get_parser():
    parser = Parser()
    parser.add_pattern(
        "successor_generator_construction_time",
        r"time for successor generation creation: ([\d.]+)s",
        type=float,
    )
    parser.add_pattern(
        "successor_generator_time",
        r"Time for successor generation: ([\d.]+)s",
        type=float,
    )
    parser.add_pattern(
        "successor_generator_calls",
        r"Successor generator calls: (\d+)",
        type=int,
    )
    return parser


def add_time_decomposition_and_shares(run):
    total = run.get("total_time")
    search = run.get("search_time")
    sg_build = run.get("successor_generator_construction_time")
    sg_query = run.get("successor_generator_time")
    translator = run.get("translator_time_done")

    if search is not None and sg_query is not None:
        run["search_rest"] = search - sg_query
    if total is not None and search is not None and sg_build is not None:
        run["downward_other"] = total - search - sg_build
    if translator is not None and total is not None:
        run["end_to_end"] = translator + total

    if sg_query is not None and search:
        run["sg_share_of_search"] = sg_query / search
    if sg_query is not None and total:
        run["sg_share_of_total"] = sg_query / total
    if sg_build is not None and sg_query is not None and total:
        run["sg_total_share_of_total"] = (sg_build + sg_query) / total
    if search is not None and total:
        run["search_share_of_total"] = search / total

    return run


def _sec(name, digits=4):
    return Attribute(name, min_wins=True, function=arithmetic_mean, digits=digits)


def _share(name, digits=4):
    return Attribute(name, min_wins=False, function=arithmetic_mean, digits=digits)


TIME_ATTRIBUTES = [
    _sec("translator_time_done"),
    _sec("successor_generator_construction_time"),
    _sec("successor_generator_time"),
    _sec("search_rest"),
    _sec("downward_other"),
    _sec("search_time"),
    _sec("total_time"),
    _sec("end_to_end"),
]

SHARE_ATTRIBUTES = [
    _share("sg_share_of_search"),
    _share("sg_share_of_total"),
    _share("sg_total_share_of_total"),
    _share("search_share_of_total"),
]

COUNT_ATTRIBUTES = [
    "coverage",
    "expansions",
    "evaluations",
    "successor_generator_calls",
    "memory",
]

ATTRIBUTES = [
    "error",
    "run_dir",
    *COUNT_ATTRIBUTES,
    *TIME_ATTRIBUTES,
    *SHARE_ATTRIBUTES,
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
    filter=[add_time_decomposition_and_shares],
)

if not project.REMOTE:
    project.add_scp_step(exp, SCP_LOGIN, REMOTE_REPOS_DIR)

exp.run_steps()
