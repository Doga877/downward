#! /usr/bin/env python

import os

from lab.parser import Parser
from lab.reports import Attribute, arithmetic_mean

import project

REPO = project.get_repo_base()
BENCHMARKS_DIR = os.environ["DOWNWARD_BENCHMARKS"]

if project.REMOTE:
    SUITE = project.SUITE_SATISFICING
    ENV = project.BaselSlurmEnvironment(email="d.oglakcioglu@unibas.ch")
else:
    SUITE = ["depot:p01.pddl", "grid:prob01.pddl", "gripper:prob01.pddl"]
    ENV = project.LocalEnvironment(processes=2)

NUM_STATES = 10000
REPETITIONS = 10
SEED = 42

CONFIGS = [
    (
        "matchtree",
        [
            "--search",
            f"sg_benchmark(num_states={NUM_STATES}, "
            f"repetitions={REPETITIONS}, seed={SEED})",
        ],
    ),
]

BUILD_OPTIONS = ["-j4"]
DRIVER_OPTIONS = ["--overall-time-limit", "5m", "--search-memory-limit", "3500M"]
REV_NICKS = [("main", "")]


def get_parser():
    parser = Parser()
    parser.add_pattern("sg_construction_time", r"SG construction time: ([\d.]+)s", type=float)
    parser.add_pattern("sg_sample_states", r"SG sample states: (\d+)", type=int)
    parser.add_pattern("sg_total_query_time", r"SG total query time: ([\d.]+)s", type=float)
    parser.add_pattern("sg_time_per_query", r"SG time per query: ([\d.]+)ns", type=float)
    parser.add_pattern("sg_nodes_total", r"SG nodes total: (\d+)", type=int)
    parser.add_pattern("sg_nodes_switch", r"SG nodes switch: (\d+)", type=int)
    parser.add_pattern("sg_nodes_fork", r"SG nodes fork: (\d+)", type=int)
    parser.add_pattern("sg_nodes_leaf", r"SG nodes leaf: (\d+)", type=int)
    parser.add_pattern("sg_estimated_memory", r"SG estimated memory: (\d+) KB", type=int)
    parser.add_pattern("sg_max_depth", r"SG max depth: (\d+)", type=int)
    return parser


def _mean(name, digits=2):
    return Attribute(name, min_wins=True, function=arithmetic_mean, digits=digits)


ATTRIBUTES = [
    "error",
    "run_dir",
    _mean("sg_construction_time", digits=4),
    "sg_sample_states",
    _mean("sg_total_query_time", digits=4),
    _mean("sg_time_per_query", digits=1),
    _mean("sg_nodes_total"),
    _mean("sg_nodes_switch"),
    _mean("sg_nodes_fork"),
    _mean("sg_nodes_leaf"),
    _mean("sg_estimated_memory"),
    _mean("sg_max_depth"),
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
exp.add_parser(get_parser())

exp.add_step("build", exp.build)
exp.add_step("start", exp.start_runs)
exp.add_step("parse", exp.parse)
exp.add_fetcher(name="fetch")

project.add_absolute_report(exp, attributes=ATTRIBUTES)

exp.run_steps()
