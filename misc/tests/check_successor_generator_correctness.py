#! /usr/bin/env python3

"""
Vergleicht die vier Successor-Generator-Implementierungen (Match Tree,
Naive, Watched Literals, Marking) lokal auf einer Auswahl kleiner Aufgaben.

Aufruf:

    python3 check_successor_generator_correctness.py [zusaetzliches_ausgabeverzeichnis]

Die Ergebnisdateien werden immer neben dieses Skript geschrieben; wird ein
Verzeichnis uebergeben, landet zusaetzlich dort eine Kopie.

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
import shutil
import subprocess
import sys
import tempfile

DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(DIR))
PROJECT = os.path.dirname(REPO)
LOG_DIR = os.path.join(DIR, "sg_correctness_logs")
SUMMARY_NAME = "successor_generator_correctness_results.txt"
REPORT_NAME = "successor_generator_correctness_report.md"

FAST_DOWNWARD = os.path.join(REPO, "fast-downward.py")

# Zwei Benchmark-Quellen: die 5 kleinen Aufgaben, die direkt im
# Fast-Downward-Repo liegen, und die grosse Benchmark-Sammlung daneben.
BENCHMARK_ROOTS = {
    "lokal": os.path.join(REPO, "misc", "tests", "benchmarks"),
    "suite": os.path.join(PROJECT, "downward-benchmarks"),
}

# (Quelle, Domainordner/Problemdatei, Suchkonfiguration)
#
# Die Aufgaben sind so gewaehlt, dass sie in Sekunden loesen, aber
# strukturell verschiedene Anforderungen an die Nachfolgegenerierung
# stellen: unterschiedlich viele Operatoren, unterschiedlich viele
# Vorbedingungen pro Operator, unterschiedlicher Verzweigungsgrad, sowie
# die beiden Sonderfaelle Axiome und bedingte Effekte.
#
# astar(blind()) ist die Standardwahl, weil ohne Heuristik am meisten
# Zustaende abgefragt werden. Wo blind zu langsam ist, steht ff.
TASKS = [
    # --- die 5 Aufgaben aus dem Fast-Downward-Repo (wie im ersten Lauf) ---
    ("lokal", "gripper/prob01.pddl", ["--search", "astar(blind())"]),
    ("lokal", "miconic/s1-0.pddl", ["--search", "astar(blind())"]),
    ("lokal", "miconic-simpleadl/s1-0.pddl", ["--search", "astar(blind())"]),
    ("lokal", "philosophers/p01-phil2.pddl", ["--search", "astar(blind())"]),
    ("lokal", "satellite/p25-HC-pfile5.pddl", ["--search", "eager_greedy([ff()])"]),
    # --- strategisch gewaehlte Aufgaben aus der Benchmark-Sammlung ---
    # wenige Vorbedingungen pro Operator, klassischer Testfall
    ("suite", "blocks/probBLOCKS-4-1.pddl", ["--search", "astar(blind())"]),
    # viele Vorbedingungen pro Operator (Blocks + Logistics kombiniert)
    ("suite", "depot/p01.pddl", ["--search", "astar(blind())"]),
    # Transportdomain, mittlerer Verzweigungsgrad
    ("suite", "driverlog/p01.pddl", ["--search", "astar(blind())"]),
    # grosse Wertebereiche pro Variable, sehr viele Abfragen
    ("suite", "grid/prob01.pddl", ["--search", "astar(blind())"]),
    # viele Objekttypen, viele Operatoren
    ("suite", "rovers/p01.pddl", ["--search", "astar(blind())"]),
    # sehr einfache Vorbedingungen, dafuer viele Operatoren
    ("suite", "movie/prob01.pddl", ["--search", "astar(blind())"]),
    # hoher Verzweigungsgrad, sehr viele Abfragen
    ("suite", "zenotravel/p03.pddl", ["--search", "astar(blind())"]),
    ("suite", "tpp/p03.pddl", ["--search", "astar(blind())"]),
    # extremer Verzweigungsgrad bei minimalen Vorbedingungen
    ("suite", "visitall-opt11-strips/problem03-full.pddl",
     ["--search", "astar(blind())"]),
    # Transport mit vielen Objekten; blind ist hier zu langsam
    ("suite", "logistics98/prob01.pddl", ["--search", "eager_greedy([ff()])"]),
    # SONDERFALL bedingte Effekte
    ("suite", "miconic-fulladl/f5-0.pddl", ["--search", "astar(blind())"]),
    # SONDERFALL Axiome (:derived)
    ("suite", "psr-middle/p01-s17-n2-l2-f30.pddl", ["--search", "astar(blind())"]),
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

# Verglichen werden immer ALLE Zustaende. Nur die Tabelle im Bericht wird
# gekuerzt, sonst waere sie bei Aufgaben mit tausenden Zustaenden unlesbar.
# Abweichende Zeilen werden dabei bevorzugt gezeigt.
MAX_TABLE_ROWS_PER_TASK = 40

# Muessen vor jedem Lauf alle geloescht werden, sonst gewinnt still
# diejenige, die zuerst in create_root() geprueft wird.
ALL_GENERATOR_ENV_VARS = [var for _, var in ALGORITHMS if var is not None]

SG_LOG_RE = re.compile(
    r"SG_LOG call=(\d+) algorithm=(\S+) state=([\d,]*) ops=([\d,]*)")


def parse_int_list(text):
    if text == "":
        return []
    return [int(x) for x in text.split(",")]


def task_identifier(root_key, task_file):
    """Eindeutiger Name fuer Log-Dateien.

    Die Quelle steht mit drin, weil es Domains wie gripper in beiden
    Benchmark-Quellen gibt und sich die Logs sonst ueberschreiben wuerden.
    """
    return root_key + "_" + task_file.replace("/", "_").replace(".pddl", "")


def run_one(root_key, task_file, search_args, algorithm_name, env_var):
    env = os.environ.copy()
    for var in ALL_GENERATOR_ENV_VARS:
        env.pop(var, None)
    if env_var is not None:
        env[env_var] = "1"
    env["DOWNWARD_SG_LOG"] = "1"

    benchmarks_dir = BENCHMARK_ROOTS[root_key]
    domain_path = os.path.join(
        benchmarks_dir, os.path.dirname(task_file), "domain.pddl")
    problem_path = os.path.join(benchmarks_dir, task_file)
    command = [sys.executable, FAST_DOWNWARD, domain_path, problem_path] + search_args

    with tempfile.TemporaryDirectory() as run_dir:
        result = subprocess.run(
            command, cwd=run_dir, env=env, capture_output=True, text=True,
            timeout=600)

    log_path = os.path.join(
        LOG_DIR,
        f"{task_identifier(root_key, task_file)}__{algorithm_name}.log")
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


def compare_task(root_key, task_file, search_args):
    ops_by_state_per_algorithm = {}
    problems = []
    for algorithm_name, env_var in ALGORITHMS:
        log_path, run_error = run_one(
            root_key, task_file, search_args, algorithm_name, env_var)
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


def classify_state(state, ops_by_state_per_algorithm):
    """Gibt (Zellen, Bewertung) fuer einen Zustand zurueck."""
    reference = ops_by_state_per_algorithm[REFERENCE_ALGORITHM]
    cells = []
    ops_seen = set()
    for algorithm_name, _ in ALGORITHMS:
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
    return cells, mark


def build_markdown_table(root_key, task_file, search_args,
                         ops_by_state_per_algorithm):
    """Baut eine Tabelle Zustand-fuer-Zustand: eine Spalte pro Generator.

    Fehlt ein Zustand bei einem Generator (andere Suchreihenfolge, siehe
    compare_task), steht dort "-" statt einer Operatorenliste -- das ist
    kein Fehler, nur ein fehlender Vergleichspunkt fuer diesen Zustand.
    """
    all_states = set()
    for ops_by_state in ops_by_state_per_algorithm.values():
        all_states.update(ops_by_state.keys())
    sorted_states = sorted(all_states)

    classified = [
        (state, *classify_state(state, ops_by_state_per_algorithm))
        for state in sorted_states
    ]
    # Abweichungen zuerst zeigen, damit sie bei gekuerzter Tabelle nicht
    # unsichtbar werden.
    deviating = [row for row in classified if row[2] == "ABWEICHUNG"]
    rest = [row for row in classified if row[2] != "ABWEICHUNG"]
    shown = (deviating + rest)[:MAX_TABLE_ROWS_PER_TASK]
    shown_in_order = [row for row in classified if row in shown]

    algorithm_names = [name for name, _ in ALGORITHMS]
    search = " ".join(search_args)

    lines = [
        f"## {root_key}: {task_file}",
        "",
        f"Suche: `{search}` &middot; {len(all_states)} Zustaende insgesamt.",
        "",
    ]
    if len(classified) > len(shown_in_order):
        lines.append(
            f"> Verglichen wurden **alle {len(all_states)} Zustaende**. Die "
            f"Tabelle zeigt davon {len(shown_in_order)} (Abweichungen immer "
            f"zuerst). Die vollstaendigen Rohdaten stehen in "
            f"`sg_correctness_logs/`.")
        lines.append("")

    lines.append("| # | Zustand | " + " | ".join(algorithm_names) + " | Gleich? |")
    lines.append("|---|---|" + "---|" * len(algorithm_names) + "---|")

    for row_number, (state, cells, mark) in enumerate(shown_in_order, start=1):
        state_str = ",".join(str(v) for v in state)
        lines.append(
            f"| {row_number} | `{state_str}` | " + " | ".join(cells) +
            f" | {mark} |")
    lines.append("")
    return "\n".join(lines)


def write_outputs(summary, markdown, extra_output_dir):
    targets = [DIR]
    if extra_output_dir is not None:
        os.makedirs(extra_output_dir, exist_ok=True)
        targets.append(extra_output_dir)
    for target in targets:
        with open(os.path.join(target, SUMMARY_NAME), "w") as summary_file:
            summary_file.write(summary + "\n")
        with open(os.path.join(target, REPORT_NAME), "w") as report_file:
            report_file.write(markdown)
    return targets


def main():
    extra_output_dir = sys.argv[1] if len(sys.argv) > 1 else None

    # Alte Logs entfernen, damit ein Bericht nie Reste eines frueheren
    # Laufs mit anderer Aufgabenliste enthaelt.
    if os.path.isdir(LOG_DIR):
        shutil.rmtree(LOG_DIR)
    os.makedirs(LOG_DIR)

    report_lines = []
    markdown_sections = []
    total_comparisons = 0
    total_problems = 0

    for root_key, task_file, search_args in TASKS:
        print(f"=== {root_key}: {task_file} ===")
        num_comparisons, problems, ops_by_state_per_algorithm = compare_task(
            root_key, task_file, search_args)
        total_comparisons += num_comparisons
        total_problems += len(problems)
        status = "OK" if not problems else f"{len(problems)} ABWEICHUNG(EN)"
        report_lines.append(
            f"{root_key}: {task_file}: {num_comparisons} Vergleiche, {status}")
        for problem in problems[:MAX_REPORTED_PROBLEMS_PER_TASK]:
            report_lines.append(f"    {problem}")
        if len(problems) > MAX_REPORTED_PROBLEMS_PER_TASK:
            report_lines.append(
                f"    ... und {len(problems) - MAX_REPORTED_PROBLEMS_PER_TASK} "
                f"weitere")
        markdown_sections.append(build_markdown_table(
            root_key, task_file, search_args, ops_by_state_per_algorithm))

    report_lines.append("")
    report_lines.append(
        f"GESAMT: {total_comparisons} Vergleiche, {total_problems} Abweichungen")

    summary = "\n".join(report_lines)
    print()
    print(summary)

    markdown = "\n".join([
        "# Nachfolgegenerierung: Vergleich der 4 Methoden Zustand fuer Zustand",
        "",
        "Match Tree, Naive, Watched Literals und Marking auf denselben "
        "Aufgaben. Fuer jeden Zustand: die sortierten Operator-IDs, die "
        "jeder Generator dafuer geliefert hat. Match Tree ist die Referenz.",
        "",
        "Erzeugt von `misc/tests/check_successor_generator_correctness.py` "
        "-- bei jedem Lauf neu geschrieben.",
        "",
        "## Zusammenfassung",
        "",
        "```",
        summary,
        "```",
        "",
        *markdown_sections,
    ])

    targets = write_outputs(summary, markdown, extra_output_dir)
    print()
    for target in targets:
        print(f"geschrieben nach: {target}")

    if total_problems > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
