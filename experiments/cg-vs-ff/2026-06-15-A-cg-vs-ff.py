#! /usr/bin/env python

import os

from lab.reports import Attribute, geometric_mean

import custom_parser
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

# Weight used for both weighted A* variants (eager_wastar/lazy_wastar).
WASTAR_WEIGHT = 2

# Heuristics that are combined with every search algorithm below. They
# cover a range of computation costs: blind() is free, goalcount() is very
# cheap, ff(...) is moderately expensive, and hm(m=2) can be expensive.
HEURISTICS = [
    ("blind", "blind()"),
    ("goalcount", "goalcount()"),
    ("ff", "ff(transform=adapt_costs(one))"),
    ("hm2", "hm(m=2)"),
]

# Search algorithms. astar() takes a single evaluator, the other algorithms
# take a list of evaluators.
SEARCH_ALGORITHMS = [
    ("astar", lambda h: f"astar({h})"),
    ("eager_greedy", lambda h: f"eager_greedy([{h}])"),
    ("eager_wastar", lambda h: f"eager_wastar([{h}], w={WASTAR_WEIGHT})"),
    ("lazy_greedy", lambda h: f"lazy_greedy([{h}])"),
    ("lazy_wastar", lambda h: f"lazy_wastar([{h}], w={WASTAR_WEIGHT})"),
]

# Cross product: every search algorithm with every heuristic.
CONFIGS = [
    (f"{algo_nick}-{h_nick}", ["--search", make_search(h)])
    for algo_nick, make_search in SEARCH_ALGORITHMS
    for h_nick, h in HEURISTICS
]

# randomize_successors and preferred_successors_first (search_algorithm.cc,
# add_successors_order_options_to_feature) are only accepted by lazy_greedy
# and lazy_wastar, not by astar/eager_greedy/eager_wastar. We add both
# options, and their combination, as extra configurations for these two
# algorithms. ff is used both as the evaluator and (via let(...) and
# preferred=[h]) as the source of preferred operators, so that
# preferred_successors_first actually changes the order in which successors
# are generated instead of being a no-op.
SUCCESSOR_ORDER_VARIANTS = [
    ("rand", "randomize_successors=true"),
    ("pref", "preferred_successors_first=true"),
    ("rand-pref", "randomize_successors=true, preferred_successors_first=true"),
]
for algo_nick, weight in [("lazy_greedy", None), ("lazy_wastar", WASTAR_WEIGHT)]:
    weight_arg = f", w={weight}" if weight is not None else ""
    for order_nick, order_opts in SUCCESSOR_ORDER_VARIANTS:
        search = (
            "let(h, ff(transform=adapt_costs(one)), "
            f"{algo_nick}([h], preferred=[h]{weight_arg}, {order_opts}))"
        )
        CONFIGS.append((f"{algo_nick}-ff-{order_nick}", ["--search", search]))

BUILD_OPTIONS = ["-j4"]
# --search-memory-limit makes Fast Downward stop the search itself
# ("search-out-of-memory") once it gets close to the cluster's per-task
# memory limit (3872M by default in BaselSlurmEnvironment), instead of being
# killed from the outside (sigkill) once the limit is exceeded.
DRIVER_OPTIONS = [
    "--overall-time-limit", "5m",
    "--search-memory-limit", "3500M",
]

REV_NICKS = [
    ("main", ""),
]

# --- Derived successor-generator attributes -----------------------------
#
# successor_generator_construction_time, successor_generator_time and
# successor_generator_calls are parsed directly from Fast Downward's output
# (custom_parser.py). All attributes below are computed from those three
# values together with total_time, expansions and evaluations:
#   - every "*_time" attribute is a duration in seconds
#   - every "*_ratio" attribute is a fraction (0..1) of total_time
#   - every "*_per_*" attribute says how many successor-generator calls
#     happen per expansion/evaluation, or how long a single call takes
#
# They are reported as geometric means over the whole suite (like
# project.EVALUATIONS_PER_TIME), because summing times or ratios over
# thousands of unrelated problems would not be meaningful.

# Time (s) to build the successor generator data structure, before the
# search starts.
SUCCESSOR_GENERATOR_CONSTRUCTION_TIME = Attribute(
    "successor_generator_construction_time",
    min_wins=True, function=geometric_mean, digits=4,
)
# Cumulative time (s) spent inside generate_applicable_ops calls while the
# search is running (does not include construction).
SUCCESSOR_GENERATOR_TIME = Attribute(
    "successor_generator_time",
    min_wins=True, function=geometric_mean, digits=4,
)
# successor_generator_time / total_time.
SUCCESSOR_GENERATOR_TIME_RATIO = Attribute(
    "successor_generator_time_ratio",
    min_wins=False, function=geometric_mean, digits=4,
)
# (successor_generator_construction_time + successor_generator_time) /
# total_time: share of the whole run spent on the successor generator in
# total, i.e. building it plus using it during the search.
SUCCESSOR_GENERATOR_TOTAL_TIME_RATIO = Attribute(
    "successor_generator_total_time_ratio",
    min_wins=False, function=geometric_mean, digits=4,
)
# total_time - successor_generator_construction_time -
# successor_generator_time: everything Fast Downward does that is *not*
# building or using the successor generator (translating the task,
# computing heuristic values, search bookkeeping, ...).
TIME_OUTSIDE_SUCCESSOR_GENERATOR = Attribute(
    "time_outside_successor_generator",
    min_wins=True, function=geometric_mean, digits=4,
)
# time_outside_successor_generator / total_time.
TIME_OUTSIDE_SUCCESSOR_GENERATOR_RATIO = Attribute(
    "time_outside_successor_generator_ratio",
    min_wins=False, function=geometric_mean, digits=4,
)
# successor_generator_time / successor_generator_calls: average time (s) for
# a single generate_applicable_ops call during the search.
SUCCESSOR_GENERATOR_AVG_TIME_PER_CALL = Attribute(
    "successor_generator_avg_time_per_call",
    min_wins=True, function=geometric_mean, digits=6,
)
# successor_generator_calls / expansions: how many successor-generator calls
# happen per expanded state. This is 1 if the generator is only called to
# generate the successors of the expanded state, and >1 for heuristics that
# call the successor generator themselves (e.g. landmark heuristics).
SUCCESSOR_GENERATOR_CALLS_PER_EXPANSION = Attribute(
    "successor_generator_calls_per_expansion",
    min_wins=False, function=geometric_mean, digits=2,
)
# successor_generator_calls / evaluations: how many successor-generator
# calls happen per state evaluated by the heuristic.
SUCCESSOR_GENERATOR_CALLS_PER_EVALUATION = Attribute(
    "successor_generator_calls_per_evaluation",
    min_wins=False, function=geometric_mean, digits=2,
)

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
    SUCCESSOR_GENERATOR_TIME_RATIO,
    SUCCESSOR_GENERATOR_TOTAL_TIME_RATIO,
    TIME_OUTSIDE_SUCCESSOR_GENERATOR,
    TIME_OUTSIDE_SUCCESSOR_GENERATOR_RATIO,
    SUCCESSOR_GENERATOR_AVG_TIME_PER_CALL,
    SUCCESSOR_GENERATOR_CALLS_PER_EXPANSION,
    SUCCESSOR_GENERATOR_CALLS_PER_EVALUATION,
    project.EVALUATIONS_PER_TIME,
]


def add_successor_generator_attributes(run):
    total_time = run.get("total_time")
    sg_construction_time = run.get("successor_generator_construction_time")
    sg_time = run.get("successor_generator_time")
    sg_calls = run.get("successor_generator_calls")
    expansions = run.get("expansions")
    evaluations = run.get("evaluations")

    if sg_time and total_time:
        run["successor_generator_time_ratio"] = sg_time / total_time

    if sg_construction_time is not None and sg_time is not None and total_time:
        sg_total_time = sg_construction_time + sg_time
        if sg_total_time:
            run["successor_generator_total_time_ratio"] = sg_total_time / total_time
            time_outside_sg = total_time - sg_total_time
            run["time_outside_successor_generator"] = time_outside_sg
            run["time_outside_successor_generator_ratio"] = (
                time_outside_sg / total_time
            )

    if sg_time and sg_calls:
        run["successor_generator_avg_time_per_call"] = sg_time / sg_calls

    if sg_calls and expansions:
        run["successor_generator_calls_per_expansion"] = sg_calls / expansions

    if sg_calls and evaluations:
        run["successor_generator_calls_per_evaluation"] = sg_calls / evaluations

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
    filter=[project.add_evaluations_per_time, add_successor_generator_attributes],
)

# A handful of curated comparisons: cost of the heuristic (astar-blind vs.
# astar-ff), eager vs. lazy search (eager_greedy-blind vs. lazy_greedy-blind),
# and the effect of randomize_successors (lazy_greedy-ff vs.
# lazy_greedy-ff-rand).
attributes = ["successor_generator_time", "time_outside_successor_generator"]
pairs = [
    ("astar-blind", "astar-ff"),
    ("eager_greedy-blind", "lazy_greedy-blind"),
    ("lazy_greedy-ff", "lazy_greedy-ff-rand"),
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
                filter=[project.add_evaluations_per_time, add_successor_generator_attributes],
                format="tex" if project.TEX else "png",
            ),
            name=f"{exp.name}-{algo1}-vs-{algo2}-{attr}{suffix}",
        )

if not project.REMOTE:
    project.add_scp_step(exp, SCP_LOGIN, REMOTE_REPOS_DIR)

exp.run_steps()
