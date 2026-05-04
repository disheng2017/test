from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from pathlib import Path

from .models import VideoInfo


class FFmpegError(RuntimeError):
    pass


def require_ffmpeg() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe") if resolve_exe(name) is None]
    if missing:
        raise FFmpegError(
            f"缺少系统依赖: {', '.join(missing)}。请安装 ffmpeg，或设置 FFMPEG_DIR 指向包含 ffmpeg.exe 的 bin 目录。"
        )


def resolve_exe(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found

    exe_name = name if name.lower().endswith(".exe") else f"{name}.exe"
    candidates: list[Path] = []

    ffmpeg_dir = os.getenv("FFMPEG_DIR")
    if ffmpeg_dir:
        candidates.append(Path(ffmpeg_dir) / exe_name)

    project_root = Path(__file__).resolve().parent.parent
    candidates.extend(
        [
            project_root / ".tools" / "ffmpeg" / "bin" / exe_name,
            project_root / "ffmpeg" / "bin" / exe_name,
        ]
    )

    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        winget_root = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        candidates.extend(winget_root.glob("Gyan.FFmpeg_*/*/bin/" + exe_name))

    for path in candidates:
        try:
            if path.exists():
                return str(path)
        except OSError:
            continue
    return None


def run_cmd(args: list[str]) -> None:
    proc = subprocess.run(resolve_args(args), capture_output=True, text=True)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise FFmpegError(f"命令失败: {' '.join(args)}\n{detail}")


def capture_cmd(args: list[str]) -> str:
    proc = subprocess.run(resolve_args(args), capture_output=True, text=True)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise FFmpegError(f"命令失败: {' '.join(args)}\n{detail}")
    return proc.stdout


def resolve_args(args: list[str]) -> list[str]:
    if not args:
        return args
    if args[0] in {"ffmpeg", "ffprobe", "ffplay"}:
        exe = resolve_exe(args[0])
        if exe:
            return [exe, *args[1:]]
    return args


def probe_video(path: str | Path) -> VideoInfo:
    require_ffmpeg()
    data = capture_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ]
    )
    meta = json.loads(data)
    stream = next((s for s in meta.get("streams", []) if s.get("codec_type") == "video"), {})
    duration = float(meta.get("format", {}).get("duration") or stream.get("duration") or 0)
    fps = _parse_fps(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1")
    return VideoInfo(
        path=str(path),
        duration=duration,
        width=int(stream.get("width") or 0),
        height=int(stream.get("height") or 0),
        fps=fps,
    )


def _parse_fps(value: str) -> float:
    if "/" in value:
        num, den = value.split("/", 1)
        den_f = float(den)
        return float(num) / den_f if den_f else 0.0
    return float(value or 0)


def extract_audio(input_path: str | Path, output_wav: str | Path) -> Path:
    require_ffmpeg()
    output = Path(output_wav)
    output.parent.mkdir(parents=True, exist_ok=True)
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(output),
        ]
    )
    return output


def cut_clip(input_path: str | Path, start: float, duration: float, output_path: str | Path, cfg: dict) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    width, height = parse_resolution(str(cfg.get("resolution", "1920x1080")))
    fps = str(cfg.get("fps", 30))
    audio_bitrate = str(cfg.get("audio_bitrate", "256k"))
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    )
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(input_path),
            "-t",
            f"{duration:.3f}",
            "-vf",
            vf,
            "-r",
            fps,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            str(output),
        ]
    )
    return output


def parse_resolution(value: str) -> tuple[int, int]:
    normalized = value.lower().replace(" ", "")
    if "x" in normalized:
        left, right = normalized.split("x", 1)
    elif ":" in normalized:
        left, right = normalized.split(":", 1)
    else:
        raise FFmpegError(f"分辨率格式不正确: {value}，请使用类似 1920x1080 的格式。")
    try:
        width = int(left)
        height = int(right)
    except ValueError as exc:
        raise FFmpegError(f"分辨率格式不正确: {value}，请使用类似 1920x1080 的格式。") from exc
    if width <= 0 or height <= 0:
        raise FFmpegError(f"分辨率必须大于 0: {value}")
    return width, height


def concat_files(files: list[Path], output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    list_file = output.with_suffix(".concat.txt")
    lines = [f"file '{p.resolve().as_posix()}'" for p in files]
    list_file.write_text("\n".join(lines), encoding="utf-8")
    run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(output)])
    return output


def make_silence(duration: float, output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=mono:sample_rate=44100",
            "-t",
            f"{max(0.1, duration):.3f}",
            "-c:a",
            "mp3",
            str(output),
        ]
    )
    return output


def audio_duration(path: str | Path) -> float:
    data = capture_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    ).strip()
    try:
        return float(data)
    except ValueError:
        return math.nan
