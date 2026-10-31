"""CLI for execution-accuracy evals, usable as a CI regression gate.

  python -m app.evals.run --connection-id 1                       # run and print results
  python -m app.evals.run --connection-id 1 --model llama3.1      # evaluate another model
  python -m app.evals.run --connection-id 1 --min-accuracy 0.7    # exit 1 below 70 %
  python -m app.evals.run --connection-id 1 --baseline latest --max-drop 0.05 --no-regressions
  python -m app.evals.run --connection-id 1 --report eval.json    # machine-readable report

Exit status: 0 = passed, 1 = a gate failed, 2 = the run itself errored.
"""

import argparse
import json
import logging
import sys

from sqlalchemy import select

from app.database import SessionLocal
from app.evals import analysis
from app.evals.runner import DEFAULT_PACE_SECONDS, create_run, execute_run
from app.models import EvalRun


def _baseline(db, connection_id: int, dataset: str, spec: str, current_id: int) -> EvalRun | None:
    if spec == "latest":
        return db.scalar(
            select(EvalRun)
            .where(
                EvalRun.connection_id == connection_id,
                EvalRun.dataset == dataset,
                EvalRun.status == "done",
                EvalRun.id != current_id,
            )
            .order_by(EvalRun.id.desc())
            .limit(1)
        )
    return db.get(EvalRun, int(spec))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a QueryPilot execution-accuracy eval.")
    parser.add_argument("--connection-id", type=int, required=True)
    parser.add_argument("--dataset", default="pagila")
    parser.add_argument("--no-memory", action="store_true", help="Don't use saved queries as examples.")
    parser.add_argument("--verify", action="store_true", help="Enable self-consistency checking for each question.")
    parser.add_argument("--model", default=None, help="Chat model to evaluate (default: the configured one).")
    parser.add_argument("--label", default=None, help="Free-text label shown in the UI (e.g. a prompt variant).")
    parser.add_argument("--pace", type=float, default=DEFAULT_PACE_SECONDS, help="Seconds between questions.")
    parser.add_argument("--min-accuracy", type=float, default=None, help="Fail if accuracy is below this (0-1).")
    parser.add_argument("--baseline", default=None, help="Run id, or 'latest', to compare against.")
    parser.add_argument("--max-drop", type=float, default=0.0, help="Allowed accuracy drop versus the baseline (0-1).")
    parser.add_argument("--no-regressions", action="store_true", help="Fail if any baseline-passing question now fails.")
    parser.add_argument("--report", default=None, help="Write a JSON report to this path.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    db = SessionLocal()
    try:
        run = create_run(
            db, args.connection_id, args.dataset,
            use_memory=not args.no_memory, verify=args.verify, model=args.model, label=args.label,
        )
        run_id = run.id
    finally:
        db.close()

    execute_run(run_id, pace_seconds=args.pace)

    db = SessionLocal()
    try:
        run = db.get(EvalRun, run_id)
        print(f"\nRun #{run.id} ({run.model}, memory={'on' if run.use_memory else 'off'}, "
              f"verify={'on' if run.verify else 'off'}): {run.passed}/{run.completed} passed — "
              f"accuracy {100 * (run.accuracy or 0):.1f}%")
        if run.status != "done":
            print(f"Run did not finish: {run.error}", file=sys.stderr)
            sys.exit(2)
        for r in run.results:
            mark = "✓" if r.passed else "✗"
            tag = f"[{r.difficulty or '-'}] "
            print(f"  {mark} {tag}{r.question}" + (f"  ({r.failure_type}: {r.error})" if not r.passed and r.error else
                                                    f"  ({r.failure_type})" if not r.passed else ""))
        stats = analysis.breakdown(run.results)
        print("\nBy difficulty: " + ", ".join(
            f"{k} {v['passed']}/{v['total']}" for k, v in stats["byDifficulty"].items()))
        if stats["failures"]:
            print("Failures: " + ", ".join(f"{k}={v}" for k, v in stats["failures"].items()))

        regressions, baseline_accuracy, comparison = 0, None, None
        if args.baseline:
            base = _baseline(db, args.connection_id, args.dataset, args.baseline, run.id)
            if base is None:
                print(f"Baseline '{args.baseline}' not found; skipping baseline gate.", file=sys.stderr)
            else:
                comparison = analysis.compare(base.results, run.results)
                regressions = comparison.summary["regressed"]
                baseline_accuracy = base.accuracy
                print(f"Versus baseline #{base.id} ({100 * (base.accuracy or 0):.1f}%): "
                      f"{comparison.summary['fixed']} fixed, {regressions} regressed")
                for item in comparison.items:
                    if item["change"] == "regressed":
                        print(f"    ↓ {item['question']}")

        reasons = analysis.gate(
            run.accuracy or 0.0,
            min_accuracy=args.min_accuracy,
            baseline_accuracy=baseline_accuracy,
            max_drop=args.max_drop,
            regressions=regressions,
            allow_regressions=not args.no_regressions,
        )
        if args.report:
            with open(args.report, "w") as f:
                json.dump(
                    {
                        "runId": run.id, "model": run.model, "accuracy": run.accuracy, "passed": run.passed,
                        "total": run.completed, "breakdown": stats, "gateFailures": reasons,
                        "comparison": comparison.as_dict() if comparison else None,
                    },
                    f, indent=2, default=str,
                )
        if reasons:
            print("\nGATE FAILED:\n  - " + "\n  - ".join(reasons), file=sys.stderr)
            sys.exit(1)
        print("\nGate passed." if (args.min_accuracy is not None or args.baseline) else "")
    finally:
        db.close()


if __name__ == "__main__":
    main()
