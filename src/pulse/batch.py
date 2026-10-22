from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pulse.contracts import Rejected


@dataclass
class Batch[T]:
    """Result of validating a set of records: what passed the contract and what didn't."""

    accepted: list[T] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)


def reject(dataset: str, key: Any, reason: str, payload: Any) -> Rejected:
    return Rejected(
        dataset=dataset,
        record_key=str(key),
        reason=reason,
        payload=json.dumps(payload, default=str)[:2000],
    )
