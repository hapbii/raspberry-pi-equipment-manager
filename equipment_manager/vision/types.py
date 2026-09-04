from __future__ import annotations

from dataclasses import dataclass


class DetectionError(RuntimeError):
    """사용자에게 안전하게 표시할 수 있는 객체 인식 오류입니다."""


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    votes: int
    frame_count: int
    duration_ms: int = 0
    memory_rss_mb: float | None = None


@dataclass(frozen=True)
class PreflightResult:
    model_path: str
    camera_backend: str
    frame_width: int
    frame_height: int
    detected_label: str | None
    confidence: float | None
    duration_ms: int
    memory_rss_mb: float | None
