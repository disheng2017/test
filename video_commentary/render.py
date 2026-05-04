from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .ffmpeg import audio_duration, resolve_args
from .models import Plan, Script


def render_video(plan: Plan, script: Script, output_path: Path, workdir: Path, cfg: dict) -> Path:
    render_dir = workdir / "render"
    render_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    render_cfg = cfg.get("render", {})
    line_by_clip = {line.clip_index: line for line in script.lines}
    insertions = []
    for clip in plan.clips:
        line = line_by_clip.get(clip.index)
        if not line or not line.voice_file:
            continue
        voice_path = Path(line.voice_file)
        if not voice_path.exists():
            continue
        insertions.append(
            {
                "voice_path": voice_path,
                "start": max(0.0, float(line.insert_start if line.insert_start is not None else clip.source_start)),
                "text": line.text,
            }
        )

    if not insertions:
        shutil.copyfile(plan.source_path, output_path)
        return output_path

    mix_full_narration(Path(plan.source_path), insertions, output_path, render_cfg)
    return output_path


def mix_full_narration(source_path: Path, insertions: list[dict], output_path: Path, cfg: dict) -> None:
    narration_volume = float(cfg.get("narration_volume", 1.0))
    original_volume = float(cfg.get("original_volume_without_narration", 1.0))
    fade = max(0.0, float(cfg.get("fade_seconds", 0.65)))
    source_fade = max(0.05, float(cfg.get("source_fade_seconds", 0.75)))
    mute_floor = max(0.0, min(1.0, float(cfg.get("original_volume_during_narration", 0.0))))
    audio_bitrate = str(cfg.get("audio_bitrate", "256k"))

    cmd = ["ffmpeg", "-y", "-i", str(source_path)]
    for item in insertions:
        cmd.extend(["-i", str(item["voice_path"])])

    filter_parts: list[str] = []
    orig_filters = [f"[0:a]aformat=sample_fmts=fltp:channel_layouts=stereo,volume={original_volume}"]
    mix_labels = []
    for index, item in enumerate(insertions, start=1):
        start = max(0.0, float(item["start"]))
        duration = max(0.1, audio_duration(item["voice_path"]))
        orig_filters.append(smooth_mute_volume_filter(start, duration, source_fade, mute_floor))

        local_fade = min(fade, duration / 3)
        fade_out_start = max(start, start + duration - local_fade)
        delay_ms = int(round(start * 1000))
        mix_label = f"narr{index}mix"
        mix_labels.append(f"[{mix_label}]")
        filter_parts.append(
            f"[{index}:a]aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"adelay={delay_ms}:all=1,volume={narration_volume},"
            f"afade=t=in:st={start:.3f}:d={local_fade:.3f},"
            f"afade=t=out:st={fade_out_start:.3f}:d={local_fade:.3f},"
            f"apad[{mix_label}]"
        )

    filter_parts.insert(0, ",".join(orig_filters) + "[orig]")
    if len(mix_labels) == 1:
        filter_parts.append(f"{mix_labels[0]}anull[narr]")
    else:
        filter_parts.append(f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=longest:normalize=0[narr]")
    filter_parts.append(f"[orig][narr]amix=inputs=2:duration=first:dropout_transition={source_fade:.3f}:normalize=0[a]")

    cmd.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "0:v",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_path),
        ]
    )
    proc = subprocess.run(resolve_args(cmd), capture_output=True, text=True)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"混音失败: {detail}")


def smooth_mute_volume_filter(start: float, duration: float, fade: float, floor: float) -> str:
    fade = max(0.05, min(fade, max(0.05, duration / 2)))
    fade_out_start = max(0.0, start - fade)
    mute_start = max(fade_out_start + 0.001, start)
    mute_end = max(mute_start + 0.001, start + duration)
    fade_in_end = mute_end + fade
    down_span = max(0.001, mute_start - fade_out_start)
    up_span = max(0.001, fade_in_end - mute_end)
    expr = (
        f"if(lt(t,{fade_out_start:.3f}),1,"
        f"if(lt(t,{mute_start:.3f}),1-(1-{floor:.4f})*(t-{fade_out_start:.3f})/{down_span:.3f},"
        f"if(lt(t,{mute_end:.3f}),{floor:.4f},"
        f"if(lt(t,{fade_in_end:.3f}),{floor:.4f}+(1-{floor:.4f})*(t-{mute_end:.3f})/{up_span:.3f},1))))"
    )
    return f"volume='{expr}':eval=frame"
