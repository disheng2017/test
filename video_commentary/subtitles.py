from __future__ import annotations

import re
from pathlib import Path

from .ffmpeg import capture_cmd, run_cmd
from .models import TranscriptSegment, VideoInfo


def load_subtitles(video_path: Path, workdir: Path, video: VideoInfo) -> list[TranscriptSegment]:
    candidates = subtitle_candidates(video_path, workdir)
    for path in candidates:
        segments = parse_subtitle_file(path)
        if segments:
            return segments

    embedded = extract_embedded_subtitle(video_path, workdir)
    if embedded:
        return embedded
    return []


def subtitle_candidates(video_path: Path, workdir: Path) -> list[Path]:
    paths: list[Path] = []
    configured = workdir / "subtitle.srt"
    paths.extend([configured, workdir / "subtitle.vtt", workdir / "subtitle.ass"])
    for suffix in (".srt", ".vtt", ".ass", ".ssa"):
        paths.append(video_path.with_suffix(suffix))
    return [path for path in paths if path.exists()]


def extract_embedded_subtitle(video_path: Path, workdir: Path) -> list[TranscriptSegment]:
    try:
        streams = capture_cmd(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "s",
                "-show_entries",
                "stream=index,codec_name",
                "-of",
                "csv=p=0",
                str(video_path),
            ]
        ).strip()
    except Exception:
        return []
    if not streams:
        return []

    out = workdir / "embedded_subtitle.srt"
    try:
        run_cmd(["ffmpeg", "-y", "-i", str(video_path), "-map", "0:s:0", str(out)])
    except Exception:
        return []
    return parse_subtitle_file(out)


def parse_subtitle_file(path: Path) -> list[TranscriptSegment]:
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    suffix = path.suffix.lower()
    if suffix in {".ass", ".ssa"}:
        return parse_ass(text)
    return parse_srt_or_vtt(text)


def parse_srt_or_vtt(text: str) -> list[TranscriptSegment]:
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    segments: list[TranscriptSegment] = []
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if timing_index < 0:
            continue
        start_raw, end_raw = lines[timing_index].split("-->", 1)
        start = parse_timecode(start_raw)
        end = parse_timecode(end_raw.split()[0])
        body = clean_subtitle_text(" ".join(lines[timing_index + 1 :]))
        if end > start and body:
            segments.append(TranscriptSegment(start=start, end=end, text=body))
    return segments


def parse_ass(text: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for line in text.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        start = parse_timecode(parts[1])
        end = parse_timecode(parts[2])
        body = clean_subtitle_text(parts[9])
        if end > start and body:
            segments.append(TranscriptSegment(start=start, end=end, text=body))
    return segments


def parse_timecode(value: str) -> float:
    value = value.strip().replace(",", ".")
    match = re.search(r"(\d+):(\d{2}):(\d{2})(?:\.(\d+))?", value)
    if not match:
        return 0.0
    hours, minutes, seconds, frac = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + float(f"0.{frac or '0'}")


def clean_subtitle_text(value: str) -> str:
    value = re.sub(r"\{\\.*?\}", "", value)
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("\\N", " ").replace("\\n", " ")
    return re.sub(r"\s+", " ", value).strip()
