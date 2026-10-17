"""CLI: python -m app.evals.run --connection-id 1 [--dataset pagila] [--no-memory] [--pace 4]"""

import argparse
import logging

from app.database import SessionLocal
from app.models import EvalRun
from app.evals.runner import DEFAULT_PACE_SECONDS, create_run, execute_run


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a QueryPilot execution-accuracy eval.")
    parser.add_argument("--connection-id", type=int, required=True)
    parser.add_argument("--dataset", default="pagila")
    parser.add_argument("--no-memory", action="store_true", help="Don't use saved queries as examples.")
    parser.add_argument("--pace", type=float, default=DEFAULT_PACE_SECONDS, help="Seconds between questions.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db = SessionLocal()
    try:
        run = create_run(db, args.connection_id, args.dataset, use_memory=not args.no_memory)
        run_id = run.id
    finally:
        db.close()

    execute_run(run_id, pace_seconds=args.pace)

    db = SessionLocal()
    try:
        run = db.get(EvalRun, run_id)
        print(f"\nRun #{run.id} ({run.model}, memory={'on' if run.use_memory else 'off'}): "
              f"{run.passed}/{run.completed} passed — accuracy {100 * (run.accuracy or 0):.1f}%")
        for r in run.results:
            mark = "✓" if r.passed else "✗"
            print(f"  {mark} {r.question}" + (f"  [{r.error}]" if r.error and not r.passed else ""))
    finally:
        db.close()


if __name__ == "__main__":
    main()
