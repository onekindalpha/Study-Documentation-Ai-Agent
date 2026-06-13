from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import time
import uuid


def safe_video_id_from_url(url: str) -> str:
    """
    Does not assume YouTube only. Produces a filesystem-safe short id.
    yt-dlp metadata will overwrite this with the real id when available.
    """
    import hashlib
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def make_run_id(input_url: str) -> str:
    return f"run_{int(time.time())}_{safe_video_id_from_url(input_url)}"


@dataclass
class RunRecord:
    run_id: str
    input_url: str
    video_id: str = ""
    source_type: str = "video_url"
    title: str = ""
    duration: float = 0.0
    created_at: float = field(default_factory=time.time)
    raw_dir: str = ""
    warnings: List[str] = field(default_factory=list)


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    source: str = "unknown"
    confidence: Optional[float] = None


@dataclass
class FrameEvidence:
    timestamp: float
    path: str
    source: str
    visual_type: str = "unknown"


@dataclass
class OCRBlock:
    text: str
    confidence: float = 0.0
    bbox: Optional[List[float]] = None


@dataclass
class OCRSegment:
    timestamp: float
    frame_path: str
    ocr_text: str
    confidence: float = 0.0
    blocks: List[OCRBlock] = field(default_factory=list)


@dataclass
class VisualCaption:
    timestamp: float
    frame_path: str
    visual_summary: str
    visible_terms: List[str] = field(default_factory=list)
    visual_type: str = "unknown"
    confidence: float = 0.0


@dataclass
class ConceptCandidate:
    text: str
    evidence: List[str]
    timestamps: List[float]
    confidence: float
    status: str = "accepted"
    reason: str = ""


@dataclass
class LectureTimelineSegment:
    start: float
    end: float
    transcript: str
    frames: List[str] = field(default_factory=list)
    ocr_text: List[str] = field(default_factory=list)
    visual_summary: List[str] = field(default_factory=list)
    candidate_concepts: List[ConceptCandidate] = field(default_factory=list)
    segment_role: str = "concept_explanation"


@dataclass
class ExtractionReport:
    run_id: str
    input_url: str
    video_id: str = ""
    title: str = ""
    duration: float = 0.0
    assets: Dict[str, Any] = field(default_factory=dict)
    scores: Dict[str, int] = field(default_factory=dict)
    accepted_concepts: List[Dict[str, Any]] = field(default_factory=list)
    rejected_false_positives: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    can_generate_draft: bool = False
    gate_reason: str = ""


def to_jsonable(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=to_jsonable), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
