"""CI gate: the rules extractor must not get worse on the hand-checked audit sample."""

from __future__ import annotations

import json
from pathlib import Path

from evals.score import AUDIT, regressions, score
from pulse.contracts import Extraction
from pulse.extract import rules

BASELINE = json.loads((AUDIT / "baseline.json").read_text())


def test_rules_extractor_meets_committed_baseline() -> None:
    assert regressions(score(), BASELINE) == []


def test_gate_fails_for_a_broken_extractor() -> None:
    """Proves the gate can fail: an extractor that never detects work mode must trip it."""

    def broken(post_id: int, text_html: str) -> Extraction:
        return rules.extract(post_id, text_html).model_copy(update={"work_mode": "unknown"})

    failures = regressions(score(broken), BASELINE)
    assert any(f.startswith("work_mode_accuracy") for f in failures)


def test_human_review_overrides_drafted_labels(tmp_path: Path) -> None:
    """A reviewer's correction must change the label that gets scored."""
    for name in ("sample.jsonl", "labels.jsonl"):
        (tmp_path / name).write_text((AUDIT / name).read_text())
    first = json.loads((AUDIT / "labels.jsonl").read_text().splitlines()[0])
    flipped = "onsite" if first["work_mode"] != "onsite" else "remote"
    review = {"post_id": first["post_id"], "agreed": False, "final": {"work_mode": flipped}}
    (tmp_path / "review.jsonl").write_text(json.dumps(review) + "\n")
    before, after = score(audit=AUDIT), score(audit=tmp_path)
    assert after["work_mode_accuracy"] != before["work_mode_accuracy"]
