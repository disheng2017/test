from __future__ import annotations

import json
import os
import site
from pathlib import Path
from typing import Any, Callable

from .models import TranscriptSegment
from .openai_http import OpenAIHTTPClient


ProgressCallback = Callable[[float, str], None]
CUDA_DLL_HANDLES: list[Any] = []


def transcribe_audio(
    audio_path: Path,
    cfg: dict[str, Any],
    progress_callback: ProgressCallback | None = None,
) -> list[TranscriptSegment]:
    transcribe_cfg = cfg.get("transcribe", {})
    provider = str(transcribe_cfg.get("provider", "auto")).lower()
    if provider in {"auto", "openai"}:
        segments = transcribe_openai(audio_path, cfg)
        if segments or provider == "openai":
            return segments
    if provider in {"auto", "local", "faster-whisper", "faster_whisper"}:
        return transcribe_faster_whisper(audio_path, cfg, progress_callback)
    return []


def transcribe_openai(audio_path: Path, cfg: dict[str, Any]) -> list[TranscriptSegment]:
    transcribe_cfg = cfg.get("transcribe", {})
    api_key = transcribe_cfg.get("api_key") or cfg.get("openai_api_key")
    if not api_key or str(api_key).startswith("sk-cp-"):
        return []

    client = OpenAIHTTPClient(api_key=api_key, base_url=transcribe_cfg.get("base_url", "https://api.openai.com/v1"))
    model = transcribe_cfg.get("model") or cfg.get("models", {}).get("transcript", "gpt-4o-mini-transcribe")
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


def transcribe_faster_whisper(
    audio_path: Path,
    cfg: dict[str, Any],
    progress_callback: ProgressCallback | None = None,
) -> list[TranscriptSegment]:
    add_cuda_dll_directories()
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "未安装本地字幕识别依赖 faster-whisper。请在项目虚拟环境中运行: "
            ".\\.venv\\Scripts\\python.exe -m pip install faster-whisper"
        ) from exc

    transcribe_cfg = cfg.get("transcribe", {})
    model_name = transcribe_cfg.get("local_model", "small")
    device = transcribe_cfg.get("device", "cpu")
    compute_type = transcribe_cfg.get("compute_type", "int8")
    beam_size = int(transcribe_cfg.get("beam_size", 5))
    best_of = int(transcribe_cfg.get("best_of", 5))
    initial_prompt = str(transcribe_cfg.get("initial_prompt", "")).strip() or None
    language = cfg.get("language", "zh")
    if progress_callback:
        progress_callback(0.02, f"正在加载 Whisper {model_name} 模型")

    try:
        return transcribe_with_model(
            WhisperModel,
            model_name,
            device,
            compute_type,
            audio_path,
            language,
            beam_size,
            best_of,
            initial_prompt,
            progress_callback,
        )
    except RuntimeError as exc:
        if device == "cuda" and "cublas64_12.dll" in str(exc):
            if progress_callback:
                progress_callback(0.1, "CUDA 运行库缺少 cuBLAS，已自动回退到 CPU 转写")
            return transcribe_with_model(
                WhisperModel,
                model_name,
                "cpu",
                "int8",
                audio_path,
                language,
                beam_size,
                best_of,
                initial_prompt,
                progress_callback,
            )
        raise


def transcribe_with_model(
    model_cls: Any,
    model_name: str,
    device: str,
    compute_type: str,
    audio_path: Path,
    language: str,
    beam_size: int,
    best_of: int,
    initial_prompt: str | None,
    progress_callback: ProgressCallback | None,
) -> list[TranscriptSegment]:
    model = model_cls(model_name, device=device, compute_type=compute_type)
    if progress_callback:
        progress_callback(0.08, f"Whisper 模型已加载到 {device}，开始识别音频")
    segments, info = run_whisper_transcribe(model, audio_path, language, beam_size, best_of, initial_prompt)
    duration = max(float(getattr(info, "duration", 0) or 0), 1.0)
    checkpoint_path = transcribe_checkpoint_path()
    results: list[TranscriptSegment] = []
    for seg in segments:
        text = str(seg.text).strip()
        if not text:
            continue
        results.append(TranscriptSegment(start=float(seg.start), end=float(seg.end), text=text))
        if checkpoint_path and len(results) % 5 == 0:
            write_transcribe_checkpoint(checkpoint_path, results)
        if progress_callback:
            ratio = min(0.98, max(0.1, float(seg.end) / duration))
            progress_callback(ratio, f"正在识别字幕：{format_seconds(seg.end)} / {format_seconds(duration)}")
    if checkpoint_path:
        write_transcribe_checkpoint(checkpoint_path, results)
    if progress_callback:
        progress_callback(1.0, "字幕识别完成，正在整理结果")
    return results


def run_whisper_transcribe(
    model: Any,
    audio_path: Path,
    language: str,
    beam_size: int,
    best_of: int,
    initial_prompt: str | None,
) -> Any:
    return model.transcribe(
        str(audio_path),
        language=language,
        vad_filter=True,
        beam_size=beam_size,
        best_of=best_of,
        initial_prompt=initial_prompt,
        condition_on_previous_text=True,
    )


def format_seconds(seconds: float) -> str:
    value = max(0, int(seconds))
    minutes, secs = divmod(value, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def add_cuda_dll_directories() -> None:
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return
    candidates: list[Path] = []
    for root in site.getsitepackages():
        nvidia_root = Path(root) / "nvidia"
        if not nvidia_root.exists():
            continue
        candidates.extend(nvidia_root.glob("*/*/bin"))
        candidates.extend(nvidia_root.glob("*/bin"))
    cuda_path = os.getenv("CUDA_PATH")
    if cuda_path:
        candidates.append(Path(cuda_path) / "bin")
    for path in candidates:
        if path.exists():
            path_text = str(path)
            if path_text not in os.environ.get("PATH", ""):
                os.environ["PATH"] = path_text + os.pathsep + os.environ.get("PATH", "")
            try:
                CUDA_DLL_HANDLES.append(os.add_dll_directory(path_text))
            except OSError:
                pass


def transcribe_checkpoint_path() -> Path | None:
    value = os.getenv("VIDEO_COMMENTARY_TRANSCRIBE_CHECKPOINT", "").strip()
    return Path(value) if value else None


def write_transcribe_checkpoint(path: Path, segments: list[TranscriptSegment]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [{"start": item.start, "end": item.end, "text": item.text} for item in segments]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
