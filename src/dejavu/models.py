from dataclasses import dataclass, field, asdict
from typing import Any

@dataclass
class ObservationWindow:
    service: str
    features: dict[str, float]
    slopes: dict[str, float] = field(default_factory=dict)
    observed_at: str | None = None

@dataclass
class CurrentSituation:
    service: str
    failure_class: str
    dependency: str | None
    trajectory: dict[str, list[float]]
    confidence: float = 0.0

@dataclass
class MemoryRecord:
    id: str
    kind: str
    service: str
    status: str = "active"
    payload: dict[str, Any] = field(default_factory=dict)
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 1.0

    def to_dict(self): return asdict(self)
