#! /usr/bin/env python

import os

import custom_parser
import project

REPO = project.get_repo_base()
BENCHMARKS_DIR = os.environ["DOWNWARD_BENCHMARKS"]
SCP_LOGIN = "oglakc0000@login.infai.org"
REMOTE_REPOS_DIR = "/infai/oglakc0000/projects"

if project.REMOTE:
    SUITE = project.SUITE_SATISFICING
    ENV = project.BaselSlurmEnvironment(email="oglakc0000@stud.unibas.ch")
else:
    SUITE = ["depot:p01.pddl", "grid:prob01.pddl", "gripper:prob01.pddl"]
    ENV = project.LocalEnvironment(processes=2)

CONFIGS = [
    (f"{index:02d}-{h_nick}", ["--search", f"eager_greedy([{h}])"])
    for index, (h_nick, h) in enumerate(
        [
            ("cg", "cg(transform=adapt_costs(one))"),
            ("ff", "ff(transform=adapt_costs(one))"),
        ],
        start=1,
    )
]
BUILD_OPTIONS = ["-j4"]
DRIVER_OPTIONS = ["--overall-time-limit", "5m"]
REV_NICKS = [
    ("main", ""),
]
ATTRIBUTES = [
    "error",
    "run_dir",
    "search_start_time",
    "search_start_memory",
    "total_time",
    "h_values",
    "coverage",
    "expansions",
    "evaluations",
    "memory",
    "successor_generator_construction_time",
    "successor_generator_time",
    "successor_generator_calls",
    "successor_generator_time_ratio",
    "successor_generator_calls_ratio",
    project.EVALUATIONS_PER_TIME,
]


def add_successor_generator_ratios(run):
    sg_time = run.get("successor_generator_time")
    total_time = run.get("total_time")
    if sg_time is not None and total_time:
        run["successor_generator_time_ratio"] = sg_time / total_time

    sg_calls = run.get("successor_generator_calls")
    evaluations = run.get("evaluations")
    if sg_calls is not None and evaluations:
        run["successor_generator_calls_ratio"] = sg_calls / evaluations

    return run

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
exp.add_parser(custom_parser.get_parser())
exp.add_parser(exp.PLANNER_PARSER)

exp.add_step("build", exp.build)
exp.add_step("start", exp.start_runs)
exp.add_step("parse", exp.parse)
exp.add_fetcher(name="fetch")

project.add_absolute_report(
    exp,
    attributes=ATTRIBUTES,
    filter=[project.add_evaluations_per_time, add_successor_generator_ratios],
)

attributes = ["expansions", "successor_generator_time"]
pairs = [
    ("01-cg", "02-ff"),
]
suffix = "-rel" if project.RELATIVE else ""
for algo1, algo2 in pairs:
    for attr in attributes:
        exp.add_report(
            project.ScatterPlotReport(
                relative=project.RELATIVE,
                get_category=None if project.TEX else lambda run1, run2: run1["domain"],
                attributes=[attr],
                filter_algorithm=[algo1, algo2],
                filter=[project.add_evaluations_per_time, add_successor_generator_ratios],
                format="tex" if project.TEX else "png",
            ),
            name=f"{exp.name}-{algo1}-vs-{algo2}-{attr}{suffix}",
        )

if not project.REMOTE:
    project.add_scp_step(exp, SCP_LOGIN, REMOTE_REPOS_DIR)

exp.run_steps()
