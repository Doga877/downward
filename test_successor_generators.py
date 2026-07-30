#!/usr/bin/env python3

import os
import re
import subprocess
import sys

BENCHMARKS = [
    ("gripper", "domain.pddl", "prob01.pddl"),
    ("miconic", "domain.pddl", "s1-0.pddl"),
    ("miconic-simpleadl", "domain.pddl", "s1-0.pddl"),
    ("philosophers", "domain.pddl", "p01-phil2.pddl"),
    ("satellite", "domain.pddl", "p25-HC-pfile5.pddl"),
]

METHODS = [
    ("match tree", {}),
    ("naive", {"DOWNWARD_SG_NAIVE": "1"}),
    ("watched literals", {"DOWNWARD_SG_WATCHED_LITERALS": "1"}),
]

SEARCH = "astar(blind())"


def run(domain, domain_file, problem_file, extra_env):
    env = dict(os.environ)
    for key in ["DOWNWARD_SG_NAIVE", "DOWNWARD_SG_WATCHED_LITERALS"]:
        env.pop(key, None)
    env["DOWNWARD_SG_COMPARE"] = "1"
    env.update(extra_env)

    base = os.path.join("misc", "tests", "benchmarks", domain)
    command = [
        sys.executable, "fast-downward.py",
        "--plan-file", os.path.join("/tmp", "plan_test"),
        os.path.join(base, domain_file),
        os.path.join(base, problem_file),
        "--search", SEARCH,
    ]
    result = subprocess.run(
        command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True)
    return result.returncode, result.stdout


def find(pattern, text):
    match = re.search(pattern, text)
    if match:
        return match.group(1)
    return None


def main():
    failures = 0
    print("%-20s %-18s %10s %10s %8s" % (
        "domain", "method", "comparisons", "plan cost", "result"))
    print("-" * 72)

    for domain, domain_file, problem_file in BENCHMARKS:
        for method_name, extra_env in METHODS:
            returncode, output = run(
                domain, domain_file, problem_file, extra_env)

            comparisons = find(r"comparisons against match tree: (\d+)", output)
            plan_cost = find(r"Plan cost: (\d+)", output)
            reported = find(r"Successor generator method: (.+)", output)
            mismatch = "MISMATCH" in output

            if mismatch or returncode != 0 or comparisons is None:
                verdict = "FAIL"
                failures += 1
            else:
                verdict = "ok"

            print("%-20s %-18s %10s %10s %8s" % (
                domain, method_name, comparisons or "-", plan_cost or "-",
                verdict))

            if verdict == "FAIL":
                print("  exit code: %s" % returncode)
                if reported is not None:
                    print("  generator reported: %s" % reported)
                for line in output.splitlines():
                    if "MISMATCH" in line or "State:" in line or \
                            "returned" in line:
                        print("  %s" % line)

    print("-" * 72)
    if failures == 0:
        print("All comparisons identical to the match tree.")
        return 0
    print("%d configuration(s) FAILED." % failures)
    return 1


if __name__ == "__main__":
    sys.exit(main())
