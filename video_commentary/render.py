from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .ffmpeg import concat_files, cut_clip, resolve_args, run_cmd
from .models import Plan, Script


def render_video(plan: Plan, script: Script, output_path: Path, workdir: Path, cfg: dict) -> Path:
    render_dir = workdir / "render"
    render_dir.mkdir(parents=True, exist_ok=True)

    line_by_clip = {line.clip_index: line for line in script.lines}
    rendered_clips: list[Path] = []
    render_cfg = cfg.get("render", {})

    for clip in plan.clips:
        raw_clip = render_dir / f"clip_{clip.index:02d}_raw.mp4"
        mixed_clip = render_dir / f"clip_{clip.index:02d}.mp4"
        cut_clip(plan.source_path, clip.source_start, clip.duration, raw_clip, render_cfg)

        line = line_by_clip.get(clip.index)
        if line and line.voice_file:
            mix_narration(raw_clip, Path(line.voice_file), mixed_clip, render_cfg)
        else:
            shutil.copyfile(raw_clip, mixed_clip)
        rendered_clips.append(mixed_clip)

    concat_video = render_dir / "concat.mp4"
    concat_files(rendered_clips, concat_video)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(concat_video),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-b:v",
            str(render_cfg.get("video_bitrate", "6000k")),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    return output_path


def mix_narration(video_path: Path, voice_path: Path, output_path: Path, cfg: dict) -> None:
    narration_volume = float(cfg.get("narration_volume", 1.0))
    original_volume = float(cfg.get("original_volume_under_narration", 0.28))
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(voice_path),
        "-filter_complex",
        (
            f"[0:a]volume={original_volume}[orig];"
            f"[1:a]volume={narration_volume},apad[narr];"
            "[orig][narr]amix=inputs=2:duration=first:dropout_transition=0[a]"
        ),
        "-map",
        "0:v",
        "-map",
        "[a]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        str(output_path),
    ]
    proc = subprocess.run(resolve_args(cmd), capture_output=True, text=True)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"混音失败: {detail}")
