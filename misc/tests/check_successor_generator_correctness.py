#! /usr/bin/env python3

"""
Vergleicht die vier Successor-Generator-Implementierungen (Match Tree,
Naive, Watched Literals, Marking) lokal auf ein paar kleinen Aufgaben.

Fuer jede Aufgabe und jeden Generator wird der Planer einmal ausgefuehrt.
Waehrend der Suche schreibt der Planer (nur wenn DOWNWARD_SG_LOG gesetzt
ist) pro Aufruf von generate_applicable_ops eine Zeile der Form

    SG_LOG call=<n> algorithm=<name> state=<v0,v1,...> ops=<id0,id1,...>

Nach dem Lauf werden die vier Log-Dateien einer Aufgabe eingelesen und pro
Generator zu {Zustand: sortierte Operatorenliste} zusammengefasst (die
Reihenfolge der Operatoren darf zwischen den Methoden legitim abweichen).
Verglichen wird ueber den Zustand, nicht ueber die Aufrufnummer: weil die
vier Methoden Operatoren in unterschiedlicher Reihenfolge liefern, bricht
A* Gleichstaende unterschiedlich auf und die vier Laeufe fragen nicht
zwingend dieselben Zustaende in derselben Reihenfolge ab. Es wird nichts an
der Suchleistung gemessen -- es geht ausschliesslich um die Frage, ob alle
vier Methoden fuer denselben Zustand dieselbe Menge anwendbarer Operatoren
liefern.
"""

import os
import re
import subprocess
import sys
import tempfile

DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(DIR))
BENCHMARKS_DIR = os.path.join(DIR, "benchmarks")
FAST_DOWNWARD = os.path.join(REPO, "fast-downward.py")
LOG_DIR = os.path.join(DIR, "sg_correctness_logs")
SUMMARY_FILE = os.path.join(DIR, "successor_generator_correctness_results.txt")
REPORT_FILE = os.path.join(DIR, "successor_generator_correctness_report.md")

# Eine einzige, kleine Aufgabe: klein genug, um im Zweifel jede geloggte
# Zeile von Hand nachzuvollziehen, aber gross genug (238 Aufrufe), um kein
# Zufallstreffer zu sein.
TASKS = [
    ("gripper/prob01.pddl", ["--search", "astar(blind())"]),
]

# (Name fuer Dateien/Ausgabe, Env-Variable, die diesen Generator anschaltet)
ALGORITHMS = [
    ("match-tree", None),
    ("naive", "DOWNWARD_SG_NAIVE"),
    ("watched-literals", "DOWNWARD_SG_WATCHED_LITERALS"),
    ("marking", "DOWNWARD_SG_MARKING"),
]

REFERENCE_ALGORITHM = "match-tree"

# Ein kaputter Generator weicht in tausenden Zustaenden ab; der Bericht
# soll trotzdem lesbar bleiben. Gezaehlt werden immer alle Abweichungen.
MAX_REPORTED_PROBLEMS_PER_TASK = 10

# Muessen vor jedem Lauf alle geloescht werden, sonst gewinnt still
# diejenige, die zuerst in create_root() geprueft wird.
ALL_GENERATOR_ENV_VARS = [var for _, var in ALGORITHMS if var is not None]

SG_LOG_RE = re.compile(
    r"SG_LOG call=(\d+) algorithm=(\S+) state=([\d,]*) ops=([\d,]*)")


def parse_int_list(text):
    if text == "":
        return []
    return [int(x) for x in text.split(",")]


def run_one(task_file, search_args, algorithm_name, env_var):
    env = os.environ.copy()
    for var in ALL_GENERATOR_ENV_VARS:
        env.pop(var, None)
    if env_var is not None:
        env[env_var] = "1"
    env["DOWNWARD_SG_LOG"] = "1"

    domain_path = os.path.join(
        BENCHMARKS_DIR, os.path.dirname(task_file), "domain.pddl")
    problem_path = os.path.join(BENCHMARKS_DIR, task_file)
    command = [sys.executable, FAST_DOWNWARD, domain_path, problem_path] + search_args

    with tempfile.TemporaryDirectory() as run_dir:
        result = subprocess.run(
            command, cwd=run_dir, env=env, capture_output=True, text=True,
            timeout=180)

    task_id = task_file.replace("/", "_").replace(".pddl", "")
    log_path = os.path.join(LOG_DIR, f"{task_id}__{algorithm_name}.log")
    with open(log_path, "w") as log_file:
        log_file.write(result.stdout)
        log_file.write(result.stderr)

    if "Solution found." not in result.stdout:
        return log_path, (
            f"kein Plan gefunden (Exitcode {result.returncode}), "
            f"siehe {os.path.relpath(log_path, REPO)}")

    return log_path, None


def parse_log(log_path):
    """Liest eine Log-Datei und gibt (zustand -> sortierte_ops, Selbstwidersprueche) zurueck.

    Ein Zustand kann theoretisch mehrfach abgefragt werden (z.B. wenn die
    Suche ihn erneut oeffnet). generate_applicable_ops ist aber eine reine
    Funktion des Zustands -- taucht derselbe Zustand zweimal mit
    unterschiedlichen Operatoren auf, ist das bereits innerhalb eines
    einzigen Laufs ein Fehler, unabhaengig vom Vergleich mit anderen
    Generatoren.
    """
    ops_by_state = {}
    self_inconsistencies = []
    with open(log_path) as log_file:
        for line in log_file:
            match = SG_LOG_RE.search(line)
            if match is None:
                continue
            state = tuple(parse_int_list(match.group(3)))
            ops = tuple(sorted(parse_int_list(match.group(4))))
            if state in ops_by_state and ops_by_state[state] != ops:
                self_inconsistencies.append(
                    f"Zustand {list(state)}: einmal Operatoren "
                    f"{list(ops_by_state[state])}, einmal {list(ops)} "
                    f"(selber Lauf, selber Generator)")
            ops_by_state[state] = ops
    return ops_by_state, self_inconsistencies


def compare_task(task_file, search_args):
    ops_by_state_per_algorithm = {}
    problems = []
    for algorithm_name, env_var in ALGORITHMS:
        log_path, run_error = run_one(
            task_file, search_args, algorithm_name, env_var)
        # Ein Lauf ohne Plan ist selbst schon ein Befund (ein verschluckter
        # Operator kann eine loesbare Aufgabe unloesbar machen). Die
        # geloggten Zustaende werden trotzdem ausgewertet, soweit vorhanden.
        if run_error is not None:
            problems.append(f"{algorithm_name}: {run_error}")
        ops_by_state, self_inconsistencies = parse_log(log_path)
        ops_by_state_per_algorithm[algorithm_name] = ops_by_state
        for issue in self_inconsistencies:
            problems.append(f"{algorithm_name}: {issue}")

    if not ops_by_state_per_algorithm[REFERENCE_ALGORITHM]:
        problems.append(
            f"{REFERENCE_ALGORITHM} hat keine Zustaende geloggt -- "
            f"ohne Referenz ist kein Vergleich moeglich")
        return 0, problems, ops_by_state_per_algorithm

    # Match Tree ist die Referenz. Ein Zustand, den eine andere Methode nie
    # abgefragt hat (oder umgekehrt), ist KEIN Fehler: A* bricht Gleichstaende
    # anhand der Operator-Reihenfolge auf, und die vier Methoden liefern
    # Operatoren legitim in unterschiedlicher Reihenfolge -- die Suchen
    # koennen dadurch unterschiedliche (aber gleich gute) Knoten expandieren.
    # Verglichen wird deshalb nur die Schnittmenge der tatsaechlich von
    # beiden Methoden abgefragten Zustaende.
    reference = ops_by_state_per_algorithm[REFERENCE_ALGORITHM]

    num_comparisons = 0
    for algorithm_name, ops_by_state in ops_by_state_per_algorithm.items():
        if algorithm_name == REFERENCE_ALGORITHM:
            continue
        only_in_algorithm = 0
        for state, ops in ops_by_state.items():
            if state not in reference:
                only_in_algorithm += 1
                continue
            num_comparisons += 1
            if ops != reference[state]:
                problems.append(
                    f"{algorithm_name} Zustand {list(state)}: Operatoren "
                    f"{list(ops)} != {list(reference[state])} "
                    f"({REFERENCE_ALGORITHM})")
        only_in_reference = sum(
            1 for state in reference if state not in ops_by_state)
        print(
            f"    [info] {algorithm_name}: {len(ops_by_state)} Zustaende "
            f"abgefragt, {only_in_algorithm} nur hier, {only_in_reference} "
            f"nur bei {REFERENCE_ALGORITHM}")

    return num_comparisons, problems, ops_by_state_per_algorithm


def format_ops(ops):
    return ",".join(str(op) for op in ops)


def build_markdown_table(task_file, ops_by_state_per_algorithm):
    """Baut eine Tabelle Zustand-fuer-Zustand: eine Spalte pro Generator.

    Fehlt ein Zustand bei einem Generator (andere Suchreihenfolge, siehe
    compare_task), steht dort "-" statt einer Operatorenliste -- das ist
    kein Fehler, nur ein fehlender Vergleichspunkt fuer diesen Zustand.
    """
    reference = ops_by_state_per_algorithm[REFERENCE_ALGORITHM]
    all_states = set()
    for ops_by_state in ops_by_state_per_algorithm.values():
        all_states.update(ops_by_state.keys())

    algorithm_names = [name for name, _ in ALGORITHMS]
    header = "| # | Zustand | " + " | ".join(algorithm_names) + " | Gleich? |"
    separator = "|---|---|" + "---|" * len(algorithm_names) + "---|"

    lines = [
        f"## {task_file} ({len(all_states)} Zustaende)",
        "",
        header,
        separator,
    ]
    for row_number, state in enumerate(sorted(all_states), start=1):
        cells = []
        ops_seen = set()
        for algorithm_name in algorithm_names:
            ops = ops_by_state_per_algorithm[algorithm_name].get(state)
            if ops is None:
                cells.append("-")
            else:
                cells.append(format_ops(ops))
                ops_seen.add(ops)
        if state not in reference:
            mark = "(kein Vergleich: match-tree hat diesen Zustand nie abgefragt)"
        elif len(ops_seen) <= 1:
            mark = "OK"
        else:
            mark = "ABWEICHUNG"
        state_str = ",".join(str(v) for v in state)
        lines.append(
            f"| {row_number} | `{state_str}` | " + " | ".join(cells) +
            f" | {mark} |")
    lines.append("")
    return "\n".join(lines)


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    report_lines = []
    markdown_sections = []
    total_comparisons = 0
    total_problems = 0

    for task_file, search_args in TASKS:
        num_comparisons, problems, ops_by_state_per_algorithm = compare_task(
            task_file, search_args)
        total_comparisons += num_comparisons
        total_problems += len(problems)
        status = "OK" if not problems else f"{len(problems)} ABWEICHUNG(EN)"
        report_lines.append(f"{task_file}: {num_comparisons} Vergleiche, {status}")
        for problem in problems[:MAX_REPORTED_PROBLEMS_PER_TASK]:
            report_lines.append(f"    {problem}")
        if len(problems) > MAX_REPORTED_PROBLEMS_PER_TASK:
            report_lines.append(
                f"    ... und {len(problems) - MAX_REPORTED_PROBLEMS_PER_TASK} "
                f"weitere")
        markdown_sections.append(
            build_markdown_table(task_file, ops_by_state_per_algorithm))

    report_lines.append("")
    report_lines.append(
        f"GESAMT: {total_comparisons} Vergleiche, {total_problems} Abweichungen")

    report = "\n".join(report_lines)
    print(report)
    with open(SUMMARY_FILE, "w") as summary_file:
        summary_file.write(report + "\n")

    markdown = "\n".join([
        "# Nachfolgegenerierung: Vergleich der 4 Methoden Zustand fuer Zustand",
        "",
        "Match Tree, Naive, Watched Literals und Marking auf denselben "
        "Aufgaben. Fuer jeden Zustand: die sortierten Operator-IDs, die "
        "jeder Generator dafuer geliefert hat. Erzeugt von "
        "check_successor_generator_correctness.py -- bei jedem Lauf neu "
        "geschrieben.",
        "",
        "## Zusammenfassung",
        "",
        "```",
        report,
        "```",
        "",
        *markdown_sections,
    ])
    with open(REPORT_FILE, "w") as report_file:
        report_file.write(markdown)

    if total_problems > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
