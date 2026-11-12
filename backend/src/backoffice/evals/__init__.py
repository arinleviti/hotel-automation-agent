"""Evals (step 14): the 10 demo emails run through the REAL system and checked against their
expected outcomes (CLAUDE.md, section 4, the email table).

    cases.py      the expected outcomes, as named checks (one list per email)
    run_evals.py  runs every email N times, applies the checks, prints and saves a report

Offline evals: run on demand (before a commit, after changing a prompt or a model), not live
monitoring. Costs real money (about $0.02 per run of all 10 emails), so they are NOT part of pytest.
    uv run python -m backoffice.evals.run_evals --runs 3
"""
