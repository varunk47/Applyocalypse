"""Scores the golden dataset and fails the build when a grader stops biting.

Run from `services/automation-python`:

    python -m evals.run_evals            # score every case
    python -m evals.run_evals --verbose  # show each grader's verdict

Exit code 1 means either a good sample was rejected or a deliberately bad one
slipped through. Both are release blockers: the first breaks users' documents,
the second means the gate is decorative.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from applyocalypse_automation.evals import GraderResult, grade_text

CASES_DIR = Path(__file__).parent / "cases"


@dataclass(frozen=True, slots=True)
class CaseOutcome:
    case_id: str
    stage: str
    ok: bool
    reason: str
    results: tuple[GraderResult, ...]


def load_suites(cases_dir: Path = CASES_DIR) -> list[dict]:
    suites = []
    for path in sorted(cases_dir.glob("*.json")):
        suite = json.loads(path.read_text(encoding="utf-8"))
        suite["path"] = path
        suites.append(suite)
    if not suites:
        raise SystemExit(f"no eval cases found in {cases_dir}")
    return suites


def score_case(suite: dict, case: dict) -> CaseOutcome:
    results = tuple(
        grade_text(
            case["output"],
            artifact_kind=suite["artifact_kind"],
            sources=list(suite["sources"].values()),
            must_mention=suite.get("must_mention"),
        )
    )
    failed = {result.name for result in results if not result.passed}
    stage = suite["stage"]

    if case["expect"] == "pass":
        if failed:
            detail = "; ".join(result.summary() for result in results if not result.passed)
            return CaseOutcome(case["id"], stage, False, f"a good sample was rejected: {detail}", results)
        return CaseOutcome(case["id"], stage, True, "accepted, as expected", results)

    expected_failures = set(case.get("expect_failing_graders", []))
    if not failed:
        return CaseOutcome(case["id"], stage, False, "a bad sample passed every grader", results)
    missing = expected_failures - failed
    if missing:
        return CaseOutcome(
            case["id"],
            stage,
            False,
            f"caught, but not by {sorted(missing)}; the intended grader stopped biting",
            results,
        )
    return CaseOutcome(case["id"], stage, True, f"rejected by {sorted(failed)}, as expected", results)


def run(cases_dir: Path = CASES_DIR) -> list[CaseOutcome]:
    return [score_case(suite, case) for suite in load_suites(cases_dir) for case in suite["cases"]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="print every grader verdict, not just failures")
    args = parser.parse_args(argv)

    outcomes = run()
    for outcome in outcomes:
        mark = "ok  " if outcome.ok else "FAIL"
        print(f"{mark} {outcome.stage}/{outcome.case_id}: {outcome.reason}")
        if args.verbose:
            for result in outcome.results:
                print(f"       {result.summary()}")
                for finding in result.findings:
                    print(f"         - {finding}")

    failures = [outcome for outcome in outcomes if not outcome.ok]
    print(f"\n{len(outcomes) - len(failures)}/{len(outcomes)} eval cases behaved as expected")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
