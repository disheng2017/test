from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from .models import Analysis, CandidateClip, Plan, PlannedClip, TranscriptSegment


def build_plan(analysis: Analysis, cfg: dict, target_minutes: float | None = None, narration_ratio: float | None = None) -> Plan:
    target_duration = float(target_minutes or cfg.get("target_minutes", 5)) * 60
    ratio = clamp(float(narration_ratio if narration_ratio is not None else cfg.get("narration_ratio", 0.45)), 0.1, 0.8)
    selection = cfg.get("selection", {})

    candidates = candidates_from_transcript(analysis.transcript, analysis.video.duration, selection)
    if not candidates:
        candidates = fallback_candidates(analysis.video.duration, target_duration, selection)

    chosen = choose_clips(candidates, target_duration, int(selection.get("max_clips", 3)))
    planned: list[PlannedClip] = []
    cursor = 0.0
    selected_total = sum(c.duration for c in chosen) or 1
    narration_budget = selected_total * ratio

    for idx, clip in enumerate(chosen, start=1):
        duration = clip.duration
        planned.append(
            PlannedClip(
                index=idx,
                source_start=clip.start,
                source_end=clip.end,
                timeline_start=cursor,
                timeline_end=cursor + duration,
                score=clip.score,
                transcript=clip.text,
                narration_target_seconds=max(4.0, narration_budget * duration / selected_total),
            )
        )
        cursor += duration

    return Plan(
        source_path=analysis.video.path,
        target_duration=sum(item.duration for item in planned),
        narration_ratio=ratio,
        clips=planned,
    )


def candidates_from_transcript(
    segments: list[TranscriptSegment],
    video_duration: float,
    cfg: dict,
) -> list[CandidateClip]:
    if not segments:
        return []

    min_s = float(cfg.get("clip_min_seconds", 35))
    max_s = float(cfg.get("clip_max_seconds", 75))
    pad = float(cfg.get("context_padding_seconds", 2))
    keywords = [str(k).lower() for k in cfg.get("keywords", [])]
    keyword_weight = float(cfg.get("motivational_keyword_weight", 1.4))
    density_weight = float(cfg.get("dialogue_density_weight", 0.8))
    coverage_weight = float(cfg.get("even_coverage_weight", 0.35))

    candidates: list[CandidateClip] = []
    for i, start_seg in enumerate(segments):
        text_parts: list[str] = []
        start = max(0.0, start_seg.start - pad)
        end = start
        for seg in segments[i:]:
            if seg.end - start > max_s:
                break
            text_parts.append(format_segment_text(seg))
            end = min(video_duration, seg.end + pad)
            if end - start >= min_s:
                text = " ".join(text_parts)
                score = score_text(text, keywords) * keyword_weight
                score += dialogue_density(text, end - start) * density_weight
                score += coverage_bonus(start, video_duration) * coverage_weight
                candidates.append(CandidateClip(start=start, end=end, score=score, text=text))
                break
    return sorted(candidates, key=lambda item: item.score, reverse=True)


def fallback_candidates(video_duration: float, target_duration: float, cfg: dict) -> list[CandidateClip]:
    max_clips = int(cfg.get("max_clips", 3))
    clip_len = clamp(target_duration / max(1, max_clips), float(cfg.get("clip_min_seconds", 35)), float(cfg.get("clip_max_seconds", 75)))
    if video_duration <= clip_len:
        return [CandidateClip(0, video_duration, 1.0, "")]
    step = max(clip_len, (video_duration - clip_len) / max(1, max_clips * 2))
    clips = []
    start = 0.0
    rank = 0
    while start + clip_len <= video_duration and len(clips) < max_clips * 3:
        # Give a mild preference to the middle third, where narrative turning points often live.
        center = (start + clip_len / 2) / max(video_duration, 1)
        score = 1.0 - abs(center - 0.55) + rank * 0.001
        clips.append(CandidateClip(start, start + clip_len, score, ""))
        start += step
        rank += 1
    return sorted(clips, key=lambda item: item.score, reverse=True)


def format_segment_text(seg: TranscriptSegment) -> str:
    if seg.role:
        return f"{seg.role}: {seg.text}"
    return seg.text


def choose_clips(candidates: Iterable[CandidateClip], target_duration: float, max_clips: int) -> list[CandidateClip]:
    chosen: list[CandidateClip] = []
    total = 0.0
    for clip in sorted(candidates, key=lambda item: item.score, reverse=True):
        if len(chosen) >= max_clips:
            break
        if total >= target_duration:
            break
        if overlaps_any(clip, chosen):
            continue
        remaining = target_duration - total
        if clip.duration > remaining and remaining >= 8:
            clip = replace(clip, end=clip.start + remaining)
        chosen.append(clip)
        total += clip.duration
    return sorted(chosen, key=lambda item: item.start)


def overlaps_any(clip: CandidateClip, chosen: list[CandidateClip]) -> bool:
    for item in chosen:
        if max(clip.start, item.start) < min(clip.end, item.end):
            return True
    return False


def score_text(text: str, keywords: list[str]) -> float:
    lowered = text.lower()
    if not lowered:
        return 0.0
    hits = sum(lowered.count(keyword) for keyword in keywords if keyword)
    return hits / max(1.0, len(text) / 80)


def dialogue_density(text: str, duration: float) -> float:
    return min(2.0, len(text.strip()) / max(1.0, duration) / 9.0)


def coverage_bonus(start: float, duration: float) -> float:
    if duration <= 0:
        return 0.0
    x = start / duration
    return 1.0 - abs(x - 0.55)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
