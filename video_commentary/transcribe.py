from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import TranscriptSegment
from .openai_http import OpenAIHTTPClient


def transcribe_audio(audio_path: Path, cfg: dict[str, Any]) -> list[TranscriptSegment]:
    api_key = cfg.get("openai_api_key")
    if not api_key:
        return []
    if str(api_key).startswith("sk-cp-"):
        return []

    client = OpenAIHTTPClient(api_key=api_key)
    model = cfg.get("models", {}).get("transcript", "gpt-4o-mini-transcribe")
    language = cfg.get("language", "zh")

    raw = client.multipart_post(
        "/audio/transcriptions",
        fields={"model": model, "language": language, "response_format": "verbose_json"},
        files={"file": audio_path},
    )
    segments = raw.get("segments") or []
    if segments:
        return [
            TranscriptSegment(
                start=float(item.get("start", 0)),
                end=float(item.get("end", 0)),
                text=str(item.get("text", "")).strip(),
            )
            for item in segments
            if str(item.get("text", "")).strip()
        ]

    text = str(raw.get("text", "")).strip()
    if text:
        return [TranscriptSegment(start=0.0, end=0.0, text=text)]
    return []
