from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class Target:
    token: str
    text: str
    app: str
    bounds: Rect


@dataclass(frozen=True)
class Issue:
    start: int
    end: int
    original: str
    suggestions: tuple[str, ...]
    explanation: str
