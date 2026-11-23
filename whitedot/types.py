from dataclasses import dataclass


@dataclass(frozen=True)
class Issue:
    start: int
    end: int
    original: str
    suggestions: tuple[str, ...]
    explanation: str
