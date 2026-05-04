from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str
    role: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class CandidateClip:
    start: float
    end: float
    score: float
    text: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class PlannedClip:
    index: int
    source_start: float
    source_end: float
    timeline_start: float
    timeline_end: float
    score: float
    transcript: str
    narration_target_seconds: float

    @property
    def duration(self) -> float:
        return max(0.0, self.timeline_end - self.timeline_start)


@dataclass
class NarrationLine:
    clip_index: int
    text: str
    target_seconds: float
    voice_file: str | None = None
    insert_start: float | None = None


@dataclass
class VideoInfo:
    path: str
    duration: float
    width: int
    height: int
    fps: float


@dataclass
class Analysis:
    video: VideoInfo
    transcript: list[TranscriptSegment] = field(default_factory=list)


@dataclass
class Plan:
    source_path: str
    target_duration: float
    narration_ratio: float
    clips: list[PlannedClip]


@dataclass
class Script:
    style: str
    lines: list[NarrationLine]


def to_plain(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    if isinstance(obj, Path):
        return str(obj)
    return obj


def segment_from_dict(data: dict[str, Any]) -> TranscriptSegment:
    return TranscriptSegment(
        start=float(data.get("start", 0)),
        end=float(data.get("end", 0)),
        text=str(data.get("text", "")).strip(),
        role=str(data.get("role", "")).strip(),
    )


def analysis_from_dict(data: dict[str, Any]) -> Analysis:
    video = data["video"]
    return Analysis(
        video=VideoInfo(
            path=video["path"],
            duration=float(video["duration"]),
            width=int(video.get("width", 0)),
            height=int(video.get("height", 0)),
            fps=float(video.get("fps", 0)),
        ),
        transcript=[segment_from_dict(item) for item in data.get("transcript", [])],
    )


def planned_clip_from_dict(data: dict[str, Any]) -> PlannedClip:
    return PlannedClip(
        index=int(data["index"]),
        source_start=float(data["source_start"]),
        source_end=float(data["source_end"]),
        timeline_start=float(data["timeline_start"]),
        timeline_end=float(data["timeline_end"]),
        score=float(data["score"]),
        transcript=str(data.get("transcript", "")),
        narration_target_seconds=float(data.get("narration_target_seconds", 0)),
    )


def plan_from_dict(data: dict[str, Any]) -> Plan:
    return Plan(
        source_path=data["source_path"],
        target_duration=float(data["target_duration"]),
        narration_ratio=float(data["narration_ratio"]),
        clips=[planned_clip_from_dict(item) for item in data.get("clips", [])],
    )


def script_from_dict(data: dict[str, Any]) -> Script:
    return Script(
        style=str(data.get("style", "")),
        lines=[
            NarrationLine(
                clip_index=int(item["clip_index"]),
                text=str(item.get("text", "")).strip(),
                target_seconds=float(item.get("target_seconds", 0)),
                voice_file=item.get("voice_file"),
                insert_start=float(item["insert_start"]) if item.get("insert_start") is not None else None,
            )
            for item in data.get("lines", [])
        ],
    )
