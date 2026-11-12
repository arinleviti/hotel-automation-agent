"""Run the evals (step 14): every demo email through the REAL system, N times, checked against its
expected outcomes (cases.py), with a report on screen and in a Markdown file.

    uv run python -m backoffice.evals.run_evals                 all 10 emails, 3 runs each
    uv run python -m backoffice.evals.run_evals --runs 1        quicker, 1 run each
    uv run python -m backoffice.evals.run_evals 06 07 08        only emails starting with these

Needs Postgres running (the room rates, prices, availability and document index are read from it)
and the API keys in .env. Costs real money: about $0.02 per run of all 10 emails.

Each run stops at approval (the graph pauses there), so nothing is approved, sent or written to the
`actions` table. The checkpointer is the in-memory one: nothing is left in Postgres either.

Why several runs per email: an LLM doesn't answer the same way every time. One good run can be
luck (step 11: #2 passed once and failed 3/3 after; step 12: #8 failed once in 7). So the report
gives PASS RATES per check, e.g. 3/3 or 2/3.

The runs' traces still go to Langfuse, tagged "eval": when a check fails, open that run's trace to
see what the model did (the report gives the thread_id).

Report saved to backend/evals/results/<date>_<time>.md
"""

# --- Where every name used in this file comes from ------------------------------------------------
# Plain Python:
import argparse                                # reads command-line options like --runs 3
import time                                    # time.perf_counter(): a stopwatch
import uuid                                    # uuid.uuid4(): a new random ID per run (its thread_id)
from collections import defaultdict            # a dict that starts every new key with a default value
from datetime import datetime                  # the date and time for the report's file name
from pathlib import Path                       # Path: a file path you can join with /

# Langfuse:
from langfuse import propagate_attributes      # names and tags the trace of each run

# OURS:
from backoffice.evals.cases import EXPECTED
from backoffice.graph.main_graph import build_graph, email_path_for, run_until_pause_or_end
from backoffice.tracing import flush_traces

# run_evals.py is at backend/src/backoffice/evals/ -> three levels up is backend/.
RESULTS_DIR = Path(__file__).resolve().parents[3] / "evals" / "results"


def run_one(graph, name: str, run: int) -> tuple[dict, str, str]:
    """
    Run one email once, up to approval. Returns (final state, thread_id, error text or "").
    A crash of the whole run (it shouldn't happen since step 13) is caught and reported, so one
    broken email doesn't stop the evals.
    """
    thread_id = str(uuid.uuid4())
    try:
        with propagate_attributes(trace_name=f"eval {name} run {run}", session_id=thread_id, tags=["eval"]):
            result = run_until_pause_or_end(graph, {"email_path": str(email_path_for(name))}, thread_id)
        return result.state, thread_id, ""
    except Exception as error:
        return {}, thread_id, f"{type(error).__name__}: {error}"


def run_evals(names: list[str], runs: int) -> str:
    """
    Run every email `runs` times, apply its checks, return the report as Markdown text.

    passed: how many runs each check passed.
    Shape: {"#3 total is $1,440.72": 3, "#8 status is not_found": 2, ...}
    failures: for each failed check, which runs failed (thread_ids, to find the traces).
    Shape: {"#8 status is not_found": ["run 2 (thread 1e72...)"], ...}
    """
    graph = build_graph()                      # in-memory checkpointer: nothing saved in Postgres
    passed: dict[str, int] = defaultdict(int)  # defaultdict(int): a new key starts at 0
    failures: dict[str, list[str]] = defaultdict(list)
    crashes: list[str] = []
    started = time.perf_counter()

    for name in names:
        for run in range(1, runs + 1):
            state, thread_id, crash = run_one(graph, name, run)
            if crash:
                crashes.append(f"{name} run {run}: {crash}")
            passed_this_run = 0
            for check in EXPECTED[name]:
                try:
                    ok = bool(check.holds(state))
                except Exception:                  # a check that can't even read the state = failed
                    ok = False
                if ok:
                    passed[check.name] += 1
                    passed_this_run += 1
                else:
                    failures[check.name].append(f"run {run} (thread {thread_id})")
            print(f"  {name} run {run}: {passed_this_run}/{len(EXPECTED[name])} checks"
                  + (f"  CRASH {crash}" if crash else ""))

    minutes = (time.perf_counter() - started) / 60
    return build_report(names, runs, passed, failures, crashes, minutes)


def build_report(names, runs, passed, failures, crashes, minutes) -> str:
    """
    The report as Markdown: the score, then one table per email (check, pass rate), then the
    failures with their runs. Example line of a table:
        | #3 total is $1,440.72 | 3/3 | ✓ |
    """
    total_checks = sum(len(EXPECTED[n]) for n in names) * runs
    total_passed = sum(passed[c.name] for n in names for c in EXPECTED[n])
    score = 100 * total_passed / total_checks if total_checks else 0
    lines = [
        f"# Eval report, {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"**{total_passed}/{total_checks} checks passed ({score:.1f}%)**: {len(names)} emails x {runs} run(s), "
        f"{minutes:.1f} minutes. Real Claude Haiku 5.5, Voyage and Postgres; each run stops at approval.",
        "",
    ]
    for name in names:
        checks = EXPECTED[name]
        email_passed = sum(passed[c.name] for c in checks)
        lines += [f"## {name}  ({email_passed}/{len(checks) * runs})", "", "| Check | Passed | |", "|---|---|---|"]
        for check in checks:
            mark = "✓" if passed[check.name] == runs else ("⚠" if passed[check.name] else "✗")
            lines.append(f"| {check.name} | {passed[check.name]}/{runs} | {mark} |")
        lines.append("")
    if failures or crashes:
        lines += ["## Failures (open the thread's trace in Langfuse, tag `eval`)", ""]
        lines += [f"- **{check}**: {', '.join(runs_failed)}" for check, runs_failed in failures.items()]
        lines += [f"- **crash** {c}" for c in crashes]
        lines.append("")
    return "\n".join(lines)


# Command line (plain Python; see main_graph.py for `if __name__ == "__main__":`).
# argparse (plain Python) reads the options typed after the command:
#   --runs 3     how many times each email runs (default 3)
#   06 07        optional: only the emails whose names start with these
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the evals on the demo emails.")
    parser.add_argument("--runs", type=int, default=3, help="runs per email (default 3)")
    parser.add_argument("only", nargs="*", help="only emails starting with these, e.g. 06 07")
    options = parser.parse_args()

    names = [n for n in EXPECTED if not options.only or any(n.startswith(p) for p in options.only)]
    print(f"Running {len(names)} email(s) x {options.runs} run(s) ...")
    report = run_evals(names, options.runs)
    flush_traces()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"{datetime.now():%Y-%m-%d_%H%M}.md"
    path.write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"Saved: {path}")
