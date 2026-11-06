"""Score an extractor against the labelled cases in data/eval_cases.jsonl.

    python scripts/evaluate.py --extractor rule
    python scripts/evaluate.py --extractor llm --show-errors

Reports per-sign precision/recall/F1, the escalation confusion matrix, and the
rate at which returned quotes are actually grounded in the message. Small
sample, honest caveat: read it as a smoke test, not a benchmark.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.escalate import decide_escalation  # noqa: E402
from app.extract import LLMExtractor, RuleExtractor  # noqa: E402
from app.signs import SIGN_IDS  # noqa: E402
from app.validate import is_grounded  # noqa: E402

CASES = ROOT / "data" / "eval_cases.jsonl"


def load_cases() -> list[dict]:
    return [
        json.loads(line)
        for line in CASES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extractor", choices=["rule", "llm"], default="rule")
    parser.add_argument("--show-errors", action="store_true")
    args = parser.parse_args()

    extractor = RuleExtractor() if args.extractor == "rule" else LLMExtractor()
    cases = load_cases()

    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    esc_tp = esc_fp = esc_fn = esc_tn = 0
    grounded = total = 0
    errors: list[str] = []

    for case in cases:
        result = extractor.extract(case["message"])
        predicted = {f.sign_id.value: f.value.value for f in result.findings}
        expected = case["expected"]

        for sign_id, value in expected.items():
            if predicted.get(sign_id) == value:
                tp[sign_id] += 1
            else:
                fn[sign_id] += 1
        for sign_id, value in predicted.items():
            if expected.get(sign_id) != value:
                fp[sign_id] += 1

        got_esc, _ = decide_escalation(result.findings)
        want_esc = case["escalate"]
        if got_esc and want_esc:
            esc_tp += 1
        elif got_esc and not want_esc:
            esc_fp += 1
        elif want_esc and not got_esc:
            esc_fn += 1
        else:
            esc_tn += 1

        for finding in result.findings:
            total += 1
            if is_grounded(finding.quote, case["message"]):
                grounded += 1

        if args.show_errors and (predicted != expected or got_esc != want_esc):
            errors.append(
                f"{case['id']}: expected {expected or '{}'} / escalate={want_esc}\n"
                f"      got      {predicted or '{}'} / escalate={got_esc}"
            )

    print(f"\nextractor: {extractor.name}   cases: {len(cases)}\n")
    print(f"{'sign':<20}{'P':>6}{'R':>6}{'F1':>7}   support")
    print("-" * 46)
    for sign_id in SIGN_IDS:
        support = tp[sign_id] + fn[sign_id]
        if support == 0 and fp[sign_id] == 0:
            continue
        precision = tp[sign_id] / (tp[sign_id] + fp[sign_id]) if tp[sign_id] + fp[sign_id] else 0.0
        recall = tp[sign_id] / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        print(f"{sign_id:<20}{precision:>6.2f}{recall:>6.2f}{f1:>7.2f}   {support}")

    print("\nescalation")
    print(f"  caught (escalate, was an emergency) : {esc_tp}")
    print(f"  missed (no escalation, was one)     : {esc_fn}   <- the dangerous cell")
    print(f"  false alarm                         : {esc_fp}")
    print(f"  correctly quiet                     : {esc_tn}")
    rate = grounded / total if total else 0.0
    print(f"\nquote grounding: {grounded}/{total} ({rate:.0%}) of returned quotes appear in the source message")

    if errors:
        print("\nmismatches")
        for error in errors:
            print(f"  {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
