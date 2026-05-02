from __future__ import annotations

import argparse
from pathlib import Path

from .config import default_workdir, load_config, read_json, write_json
from .ffmpeg import extract_audio, probe_video
from .models import (
    Analysis,
    Script,
    analysis_from_dict,
    plan_from_dict,
    script_from_dict,
    to_plain,
)
from .render import render_video
from .scriptgen import generate_script
from .selection import build_plan
from .subtitles import load_subtitles
from .transcribe import transcribe_audio
from .tts import synthesize_voice


def main() -> None:
    parser = argparse.ArgumentParser(prog="video_commentary", description="自动生成励志题材视频解说短片")
    sub = parser.add_subparsers(dest="command", required=True)

    add_run_parser(sub)
    add_analyze_parser(sub)
    add_plan_parser(sub)
    add_script_parser(sub)
    add_voice_parser(sub)
    add_render_parser(sub)
    add_web_parser(sub)

    args = parser.parse_args()
    cfg = load_config(getattr(args, "config", None))

    if args.command == "run":
        run_pipeline(args, cfg)
    elif args.command == "analyze":
        command_analyze(args, cfg)
    elif args.command == "plan":
        command_plan(args, cfg)
    elif args.command == "script":
        command_script(args, cfg)
    elif args.command == "voice":
        command_voice(args, cfg)
    elif args.command == "render":
        command_render(args, cfg)
    elif args.command == "web":
        from .web import main as web_main

        web_main(args.config, args.host, args.port)


def add_common_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default=None, help="YAML 配置文件路径")


def add_run_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("run", help="完整运行 analyze/plan/script/voice/render")
    add_common_config(p)
    p.add_argument("--input", required=True, help="输入视频路径")
    p.add_argument("--output", required=True, help="输出视频路径")
    p.add_argument("--workdir", default=None, help="中间文件目录")
    p.add_argument("--target-minutes", type=float, default=None, help="目标成片分钟数")
    p.add_argument("--narration-ratio", type=float, default=None, help="旁白比例 0.1-0.8")
    p.add_argument("--style", default=None, help="覆盖 style.name")


def add_analyze_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("analyze", help="提取音频并转写")
    add_common_config(p)
    p.add_argument("--input", required=True)
    p.add_argument("--workdir", required=True)


def add_plan_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("plan", help="根据分析结果选择精彩片段")
    add_common_config(p)
    p.add_argument("--analysis", required=True)
    p.add_argument("--workdir", required=True)
    p.add_argument("--target-minutes", type=float, default=None)
    p.add_argument("--narration-ratio", type=float, default=None)


def add_script_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("script", help="生成解说稿")
    add_common_config(p)
    p.add_argument("--plan", required=True)
    p.add_argument("--workdir", required=True)
    p.add_argument("--style", default=None)


def add_voice_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("voice", help="生成旁白音频")
    add_common_config(p)
    p.add_argument("--script", required=True)
    p.add_argument("--workdir", required=True)


def add_render_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("render", help="合成最终视频")
    add_common_config(p)
    p.add_argument("--plan", required=True)
    p.add_argument("--script", required=True)
    p.add_argument("--voice", default=None, help="旁白目录；通常不需要传")
    p.add_argument("--workdir", default=None)
    p.add_argument("--output", required=True)


def add_web_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("web", help="启动本地网页版工作台")
    add_common_config(p)
    p.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    p.add_argument("--port", type=int, default=7860, help="监听端口，默认 7860")


def run_pipeline(args: argparse.Namespace, cfg: dict) -> None:
    if args.style:
        cfg["style"]["name"] = args.style
    workdir = Path(args.workdir) if args.workdir else default_workdir(args.input, cfg.get("workdir", ".runs"))

    analysis = analyze_video(Path(args.input), workdir, cfg)
    plan = build_plan(analysis, cfg, args.target_minutes, args.narration_ratio)
    write_json(workdir / "plan.json", to_plain(plan))

    script = generate_script(plan, cfg)
    write_json(workdir / "script.json", to_plain(script))

    script = synthesize_voice(script, workdir / "voice", cfg)
    write_json(workdir / "script.json", to_plain(script))

    output = render_video(plan, script, Path(args.output), workdir, cfg)
    print(f"完成: {output}")


def command_analyze(args: argparse.Namespace, cfg: dict) -> None:
    analysis = analyze_video(Path(args.input), Path(args.workdir), cfg)
    print(f"分析完成: {Path(args.workdir) / 'analysis.json'}")
    print(f"转写段落: {len(analysis.transcript)}")


def command_plan(args: argparse.Namespace, cfg: dict) -> None:
    analysis = analysis_from_dict(read_json(Path(args.analysis)))
    plan = build_plan(analysis, cfg, args.target_minutes, args.narration_ratio)
    out = Path(args.workdir) / "plan.json"
    write_json(out, to_plain(plan))
    print(f"选段完成: {out}")


def command_script(args: argparse.Namespace, cfg: dict) -> None:
    if args.style:
        cfg["style"]["name"] = args.style
    plan = plan_from_dict(read_json(Path(args.plan)))
    script = generate_script(plan, cfg)
    out = Path(args.workdir) / "script.json"
    write_json(out, to_plain(script))
    print(f"文案完成: {out}")


def command_voice(args: argparse.Namespace, cfg: dict) -> None:
    script = script_from_dict(read_json(Path(args.script)))
    script = synthesize_voice(script, Path(args.workdir) / "voice", cfg)
    out = Path(args.workdir) / "script.json"
    write_json(out, to_plain(script))
    print(f"旁白完成: {Path(args.workdir) / 'voice'}")


def command_render(args: argparse.Namespace, cfg: dict) -> None:
    plan = plan_from_dict(read_json(Path(args.plan)))
    script = script_from_dict(read_json(Path(args.script)))
    workdir = Path(args.workdir) if args.workdir else Path(args.plan).parent
    output = render_video(plan, script, Path(args.output), workdir, cfg)
    print(f"完成: {output}")


def analyze_video(input_path: Path, workdir: Path, cfg: dict) -> Analysis:
    workdir.mkdir(parents=True, exist_ok=True)
    video = probe_video(input_path)
    transcript = load_subtitles(input_path, workdir, video)
    if not transcript:
        audio_path = extract_audio(input_path, workdir / "audio.wav")
        transcript = transcribe_audio(audio_path, cfg)
    analysis = Analysis(video=video, transcript=transcript)
    write_json(workdir / "transcript.json", [to_plain(item) for item in transcript])
    write_json(workdir / "analysis.json", to_plain(analysis))
    return analysis
