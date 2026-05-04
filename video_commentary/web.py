from __future__ import annotations

import time
import uuid
import shutil
import threading
import traceback
import subprocess
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from .config import load_config, read_json, write_json
from .ffmpeg import FFmpegError, extract_audio, probe_video, require_ffmpeg, resolve_exe
from .models import Analysis, NarrationLine, Script, TranscriptSegment, analysis_from_dict, plan_from_dict, script_from_dict, to_plain
from .openai_http import OpenAIHTTPClient, chat_text, response_text
from .render import render_video
from .scriptgen import generate_script
from .selection import build_plan
from .subtitles import load_subtitles
from .transcribe import transcribe_audio
from .tts import minimax_clone_voice, synthesize_voice


APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = APP_ROOT.parent
WEB_ROOT = PROJECT_ROOT / ".web"
UPLOAD_ROOT = WEB_ROOT / "uploads"
PROJECTS_ROOT = WEB_ROOT / "projects"
TEST_ROOT = WEB_ROOT / "tests"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.example.yaml"


@dataclass
class ProjectState:
    id: str
    name: str
    stage: str = "created"
    status: str = "draft"
    message: str = ""
    input_path: str = ""
    output_path: str = ""
    workdir: str = ""
    subtitle_path: str = ""
    target_minutes: float = 5
    narration_ratio: float = 0.45
    protagonist: str = ""
    narrative_perspective: str = "third"
    style_name: str = "soldiers_forest_gump_dead_poets"
    style_prompt: str = ""
    llm_provider: str = "openai-compatible"
    llm_base_url: str = ""
    llm_model: str = ""
    tts_provider: str = ""
    tts_base_url: str = ""
    tts_model: str = ""
    tts_voice: str = ""
    transcribe_provider: str = ""
    whisper_model: str = ""
    whisper_beam_size: int = 5
    whisper_initial_prompt: str = ""
    progress: int = 0
    active_task: str = ""
    debug_events: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


def create_app(config_path: str | None = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024 * 1024
    app.config["VIDEO_COMMENTARY_CONFIG"] = config_path or (str(DEFAULT_CONFIG_PATH) if DEFAULT_CONFIG_PATH.exists() else None)
    create_app._config_path = app.config["VIDEO_COMMENTARY_CONFIG"]  # type: ignore[attr-defined]

    @app.get("/")
    def index():
        cfg = load_config(app.config["VIDEO_COMMENTARY_CONFIG"])
        return render_template(
            "index.html",
            api_key_present=bool(cfg.get("llm", {}).get("api_key") or cfg.get("openai_api_key")),
            ffmpeg_present=ffmpeg_ok(),
        )

    @app.get("/api/status")
    def get_status():
        ffmpeg_path = resolve_exe("ffmpeg")
        ffprobe_path = resolve_exe("ffprobe")
        cfg = load_config(app.config["VIDEO_COMMENTARY_CONFIG"])
        return jsonify(
            {
                "project_root": str(PROJECT_ROOT),
                "ffmpeg": ffmpeg_path,
                "ffprobe": ffprobe_path,
                "ffmpeg_ok": bool(ffmpeg_path and ffprobe_path),
                "llm_base_url": cfg.get("llm", {}).get("base_url", ""),
                "llm_model": cfg.get("llm", {}).get("model", ""),
                "llm_presets": llm_presets(),
                "tts_base_url": cfg.get("tts", {}).get("base_url", ""),
                "tts_provider": cfg.get("tts_provider", ""),
                "tts_model": cfg.get("tts", {}).get("model", ""),
                "tts_voice": cfg.get("tts", {}).get("voice", ""),
                "transcribe_provider": cfg.get("transcribe", {}).get("provider", "auto"),
                "transcribe_model": cfg.get("transcribe", {}).get("model", ""),
                "whisper_model": cfg.get("transcribe", {}).get("local_model", ""),
                "faster_whisper_installed": faster_whisper_installed(),
            }
        )

    @app.get("/api/gpu")
    def get_gpu():
        return jsonify(gpu_status())

    @app.post("/api/test/llm")
    def test_llm():
        payload = request.json or {}
        cfg = load_config(app.config["VIDEO_COMMENTARY_CONFIG"])
        llm_cfg = cfg.get("llm", {})
        api_key = payload.get("api_key") or llm_cfg.get("api_key")
        base_url = payload.get("base_url") or llm_cfg.get("base_url")
        model = payload.get("model") or llm_cfg.get("model")
        if not api_key:
            return jsonify({"ok": False, "message": "缺少 LLM_API_KEY"}), 400
        try:
            client = OpenAIHTTPClient(api_key=api_key, base_url=base_url)
            if "api.openai.com" in str(base_url):
                data = client.json_post(
                    "/responses",
                    {"model": model, "input": "Reply exactly: model connection successful."},
                )
                text = response_text(data)
            else:
                data = client.json_post(
                    "/chat/completions",
                    {
                        "model": model,
                        "messages": [{"role": "user", "content": "Reply exactly: model connection successful."}],
                        "max_tokens": 128,
                    },
                )
                text = chat_text(data)
            return jsonify({"ok": True, "message": "LLM 连接成功", "model": model, "response": text[:200]})
        except Exception as exc:
            return jsonify({"ok": False, "message": friendly_llm_error(exc, base_url, model), "model": model}), 500

    @app.post("/api/test/tts")
    def test_tts():
        payload = request.json or {}
        cfg = load_config(app.config["VIDEO_COMMENTARY_CONFIG"])
        cfg["tts_provider"] = payload.get("provider") or cfg.get("tts_provider", "openai")
        cfg["tts"]["api_key"] = payload.get("api_key") or cfg.get("tts", {}).get("api_key")
        cfg["tts"]["base_url"] = payload.get("base_url") or cfg.get("tts", {}).get("base_url")
        cfg["tts"]["model"] = payload.get("model") or cfg.get("tts", {}).get("model")
        cfg["tts"]["voice"] = payload.get("voice") or cfg.get("tts", {}).get("voice")
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        try:
            script = Script(
                style="test",
                lines=[NarrationLine(clip_index=1, text="你好，配音连接成功。", target_seconds=3)],
            )
            script = synthesize_voice(script, TEST_ROOT / "voice", cfg)
            voice_file = Path(script.lines[0].voice_file or "")
            return jsonify(
                {
                    "ok": True,
                    "message": "TTS 连接成功",
                    "provider": cfg["tts_provider"],
                    "model": cfg["tts"]["model"],
                    "voice": cfg["tts"]["voice"],
                    "audio_url": url_for("get_test_voice", filename=voice_file.name),
                }
            )
        except Exception as exc:
            return jsonify({"ok": False, "message": str(exc)}), 500

    @app.post("/api/test/voice-preview")
    def preview_voice():
        payload = request.json or {}
        cfg = load_config(app.config["VIDEO_COMMENTARY_CONFIG"])
        cfg["tts_provider"] = payload.get("provider") or cfg.get("tts_provider", "openai")
        cfg["tts"]["api_key"] = payload.get("api_key") or cfg.get("tts", {}).get("api_key")
        cfg["tts"]["base_url"] = payload.get("base_url") or cfg.get("tts", {}).get("base_url")
        cfg["tts"]["model"] = payload.get("model") or cfg.get("tts", {}).get("model")
        cfg["tts"]["voice"] = payload.get("voice") or cfg.get("tts", {}).get("voice")
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        try:
            text = str(payload.get("text") or "你好，配音连接成功。")
            script = Script(style="preview", lines=[NarrationLine(clip_index=1, text=text, target_seconds=3)])
            script = synthesize_voice(script, TEST_ROOT / "voice", cfg)
            voice_file = Path(script.lines[0].voice_file or "")
            audio_url = url_for("get_test_voice", filename=voice_file.name) + f"?v={int(time.time())}"
            return jsonify(
                {
                    "ok": True,
                    "message": "音色试听已生成",
                    "provider": cfg["tts_provider"],
                    "model": cfg["tts"]["model"],
                    "voice": cfg["tts"]["voice"],
                    "audio_url": audio_url,
                }
            )
        except Exception as exc:
            return jsonify({"ok": False, "message": str(exc)}), 500

    @app.post("/api/voices/clone")
    def clone_voice():
        cfg = load_config(app.config["VIDEO_COMMENTARY_CONFIG"])
        audio_file = request.files.get("audio")
        voice_id = request.form.get("voice_id", "").strip()
        if not audio_file or not audio_file.filename:
            return jsonify({"ok": False, "message": "请上传一段用于克隆的音频"}), 400
        if not voice_id:
            voice_id = f"custom_{uuid.uuid4().hex[:10]}"
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        filename = secure_filename(audio_file.filename) or "voice_sample.mp3"
        sample_path = TEST_ROOT / filename
        audio_file.save(sample_path)
        try:
            cloned_id = minimax_clone_voice(
                sample_path,
                cfg.get("tts", {}).get("api_key", ""),
                cfg.get("tts", {}).get("base_url", "https://api.minimaxi.com/v1"),
                voice_id,
            )
            return jsonify({"ok": True, "voice_id": cloned_id, "message": "声音克隆已创建"})
        except Exception as exc:
            return jsonify({"ok": False, "message": str(exc)}), 500

    @app.get("/api/test/voice/<filename>")
    def get_test_voice(filename: str):
        path = TEST_ROOT / "voice" / secure_filename(filename)
        if not path.exists():
            return jsonify({"error": "音频不存在"}), 404
        return send_file(path, mimetype="audio/mpeg")

    @app.get("/api/projects")
    def list_projects():
        projects = [project_response(project) for project in load_all_projects()]
        projects.sort(key=lambda item: item["updated_at"], reverse=True)
        return jsonify(projects)

    @app.post("/api/projects")
    def create_project():
        video_file = request.files.get("video")
        subtitle_file = request.files.get("subtitle")
        source_path = request.form.get("source_path", "").strip()
        name = request.form.get("name", "").strip() or "励志解说项目"

        project_id = uuid.uuid4().hex[:12]
        upload_dir = UPLOAD_ROOT / project_id
        upload_dir.mkdir(parents=True, exist_ok=True)

        if video_file and video_file.filename:
            filename = secure_filename(video_file.filename) or "input.mp4"
            input_path = upload_dir / filename
            video_file.save(input_path)
            if name == "励志解说项目":
                name = Path(filename).stem
        elif source_path:
            input_path = Path(source_path)
            if not input_path.exists():
                return jsonify({"error": "源视频路径不存在"}), 400
            if name == "励志解说项目":
                name = input_path.stem
        else:
            return jsonify({"error": "请上传视频或填写本机视频路径"}), 400

        workdir = PROJECTS_ROOT / project_id
        workdir.mkdir(parents=True, exist_ok=True)
        subtitle_path = save_subtitle_file(subtitle_file, workdir)
        cfg = load_config(app.config["VIDEO_COMMENTARY_CONFIG"])
        project = ProjectState(
            id=project_id,
            name=name,
            input_path=str(input_path),
            output_path=str(workdir / "output.mp4"),
            workdir=str(workdir),
            subtitle_path=str(subtitle_path or ""),
            protagonist="",
            narrative_perspective="third",
            style_prompt=default_style_prompt(),
            llm_base_url=cfg.get("llm", {}).get("base_url", ""),
            llm_model=cfg.get("llm", {}).get("model", ""),
            tts_provider=cfg.get("tts_provider", ""),
            tts_base_url=cfg.get("tts", {}).get("base_url", ""),
            tts_model=cfg.get("tts", {}).get("model", ""),
            tts_voice=cfg.get("tts", {}).get("voice", ""),
            transcribe_provider=cfg.get("transcribe", {}).get("provider", "auto"),
            whisper_model=cfg.get("transcribe", {}).get("local_model", "small"),
            whisper_beam_size=int(cfg.get("transcribe", {}).get("beam_size", 5)),
            whisper_initial_prompt=cfg.get("transcribe", {}).get("initial_prompt", ""),
        )
        save_project(project)
        return jsonify(project_response(project))

    @app.patch("/api/projects/<project_id>")
    def update_project(project_id: str):
        project = require_project(project_id)
        payload = request.json or {}
        if "name" in payload:
            project.name = str(payload.get("name") or project.name).strip() or project.name
        update_project_options(project, payload)
        set_project(project, message="项目已更新", error=None)
        return jsonify(project_response(project))

    @app.delete("/api/projects/<project_id>")
    def delete_project(project_id: str):
        project = require_project(project_id)
        workdir = Path(project.workdir)
        upload_path = Path(project.input_path).parent
        if workdir.exists() and workdir.is_relative_to(PROJECTS_ROOT):
            shutil.rmtree(workdir)
        if upload_path.exists() and upload_path.is_relative_to(UPLOAD_ROOT):
            shutil.rmtree(upload_path)
        return jsonify({"ok": True})

    @app.get("/api/projects/<project_id>")
    def get_project(project_id: str):
        project = load_project(project_id)
        if project is None:
            return jsonify({"error": "项目不存在"}), 404
        return jsonify(project_response(project))

    @app.post("/api/projects/<project_id>/analyze")
    def analyze_project(project_id: str):
        project = require_project(project_id)
        if project.status == "running":
            return jsonify({"error": "当前已有任务在运行"}), 409
        set_project(project, stage="素材分析", status="running", active_task="analyze", progress=5, message="准备分析素材", error=None)
        start_background(run_analyze_project, project_id)
        return jsonify(project_response(project))

    @app.post("/api/projects/<project_id>/script")
    def generate_project_script(project_id: str):
        project = require_project(project_id)
        if project.status == "running":
            return jsonify({"error": "当前已有任务在运行"}), 409
        update_project_options(project, request.json or {})
        if not (Path(project.workdir) / "analysis.json").exists():
            return jsonify({"error": "请先完成素材分析，再生成文案"}), 400
        set_project(project, stage="文案生成", status="running", active_task="script", progress=5, message="准备生成解说文案", error=None)
        start_background(run_script_project, project_id)
        return jsonify(project_response(project))

    @app.put("/api/projects/<project_id>/script")
    def save_project_script(project_id: str):
        project = require_project(project_id)
        payload = request.json or {}
        lines = [
            NarrationLine(
                clip_index=int(item["clip_index"]),
                text=str(item.get("text", "")).strip(),
                target_seconds=float(item.get("target_seconds", 0)),
                voice_file=item.get("voice_file"),
                insert_start=float(item["insert_start"]) if item.get("insert_start") is not None else None,
            )
            for item in payload.get("lines", [])
        ]
        script = Script(style=project.style_name, lines=lines)
        write_json(Path(project.workdir) / "script.json", to_plain(script))
        set_project(project, stage="文案审核", status="draft", message="文案已保存")
        return jsonify(project_response(project))

    @app.put("/api/projects/<project_id>/transcript")
    def save_project_transcript(project_id: str):
        project = require_project(project_id)
        workdir = Path(project.workdir)
        analysis_path = workdir / "analysis.json"
        if not analysis_path.exists():
            return jsonify({"error": "请先完成字幕提取，再编辑字幕"}), 400
        payload = request.json or {}
        analysis = analysis_from_dict(read_json(analysis_path))
        segments = [
            TranscriptSegment(
                start=float(item.get("start", 0)),
                end=float(item.get("end", 0)),
                text=str(item.get("text", "")).strip(),
                role=str(item.get("role", "")).strip(),
            )
            for item in payload.get("transcript", [])
            if str(item.get("text", "")).strip()
        ]
        segments.sort(key=lambda item: item.start)
        analysis.transcript = segments
        write_json(workdir / "transcript.json", [to_plain(item) for item in segments])
        write_json(analysis_path, to_plain(analysis))
        write_srt(workdir / "subtitle_edited.srt", segments)
        # The plan and script depend on subtitles; make users regenerate them after edits.
        for stale in ("plan.json", "script.json"):
            path = workdir / stale
            if path.exists():
                path.unlink()
        voice_dir = workdir / "voice"
        if voice_dir.exists():
            shutil.rmtree(voice_dir)
        set_project(project, stage="字幕校准", status="draft", message=f"字幕已保存，共 {len(segments)} 段。请重新生成文案。", error=None)
        return jsonify(project_response(project))

    @app.post("/api/projects/<project_id>/voice")
    def generate_project_voice(project_id: str):
        project = require_project(project_id)
        if project.status == "running":
            return jsonify({"error": "当前已有任务在运行"}), 409
        update_project_options(project, request.json or {})
        if not (Path(project.workdir) / "script.json").exists():
            return jsonify({"error": "请先生成并保存文案"}), 400
        set_project(project, stage="配音生成", status="running", active_task="voice", progress=3, message="准备生成旁白音频", error=None)
        start_background(run_voice_project, project_id)
        return jsonify(project_response(project))

    @app.post("/api/projects/<project_id>/render")
    def render_project(project_id: str):
        project = require_project(project_id)
        if project.status == "running":
            return jsonify({"error": "当前已有任务在运行"}), 409
        workdir = Path(project.workdir)
        plan_path = workdir / "plan.json"
        script_path = workdir / "script.json"
        if not plan_path.exists() or not script_path.exists():
            return jsonify({"error": "缺少选段计划或文案"}), 400
        script = script_from_dict(read_json(script_path))
        missing_voice = [line.clip_index for line in script.lines if not line.voice_file or not Path(line.voice_file).exists()]
        if missing_voice:
            return jsonify({"error": f"这些段落还没有配音: {missing_voice[:8]}"}), 400
        project.output_path = str(workdir / f"output_{int(time.time())}.mp4")
        set_project(project, stage="导出成片", status="running", active_task="render", progress=5, message="准备合成最终视频", error=None)
        start_background(run_render_project, project_id)
        return jsonify(project_response(project))

    @app.get("/api/projects/<project_id>/artifact/<name>")
    def get_artifact(project_id: str, name: str):
        project = require_project(project_id)
        paths = artifact_paths(project)
        path = paths.get(name)
        if path is None or not path.exists():
            return jsonify({"error": "文件不存在"}), 404
        return send_file(path, as_attachment=name != "output", download_name=path.name)

    @app.get("/api/projects/<project_id>/voice/<filename>")
    def get_voice(project_id: str, filename: str):
        project = require_project(project_id)
        path = Path(project.workdir) / "voice" / secure_filename(filename)
        if not path.exists():
            return jsonify({"error": "音频不存在"}), 404
        return send_file(path, mimetype="audio/mpeg")

    return app


def llm_presets() -> list[dict[str, str]]:
    return [
        {
            "id": "minimax-m2-7",
            "label": "MiniMax 2.7",
            "base_url": "https://api.minimaxi.com/v1",
            "model": "MiniMax-M2.7",
        },
        {
            "id": "xiaomi-mimo",
            "label": "小米 MiMo",
            "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "model": "mimo-v2.5-pro",
        },
        {
            "id": "custom",
            "label": "自定义",
            "base_url": "",
            "model": "",
        },
    ]


def friendly_llm_error(exc: Exception, base_url: str, model: str) -> str:
    text = str(exc)
    lowered = text.lower()
    if "10054" in text or "remote end closed connection" in lowered or "forcibly closed" in lowered:
        return (
            f"模型连接被远端关闭。当前请求地址 {base_url}，模型 {model}。"
            "常见原因是 Base URL 与模型/Key 不匹配、服务端拒绝当前网络连接、代理或 TLS 连接被中断。"
            "可以先切换 MiniMax 2.7 或小米 MiMo 预设，再确认对应平台的 API Key 是否写在 LLM_API_KEY。"
        )
    return text


def ffmpeg_ok() -> bool:
    try:
        require_ffmpeg()
        return True
    except FFmpegError:
        return False


def faster_whisper_installed() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except ImportError:
        return False


def start_background(target: Any, project_id: str) -> None:
    thread = threading.Thread(target=target, args=(project_id,), daemon=True)
    thread.start()


def run_analyze_project(project_id: str) -> None:
    project = require_project(project_id)
    cfg = project_config(project)
    workdir = Path(project.workdir)
    try:
        set_project(project, progress=10, message="读取视频信息")
        video = probe_video(project.input_path)
        set_project(project, progress=25, message="查找外挂字幕和内嵌字幕")
        transcript = load_subtitles(Path(project.input_path), workdir, video)
        if not transcript:
            set_project(project, progress=42, message="没有可用字幕，正在提取音频")
            audio_path = extract_audio(project.input_path, workdir / "audio.wav")
            set_project(project, progress=55, message="正在从音轨自动识别字幕，长视频会比较久")

            def on_transcribe_progress(ratio: float, message: str) -> None:
                progress = 55 + int(max(0.0, min(1.0, ratio)) * 40)
                set_project(project, progress=min(95, progress), message=message)

            transcript = transcribe_audio_isolated(audio_path, workdir, project, on_transcribe_progress)
        if not transcript:
            raise RuntimeError("未能提取字幕。请确认视频有清晰音轨，或上传 SRT/VTT/ASS 字幕文件。")
        set_project(project, progress=96, message=f"正在整理 {len(transcript)} 段字幕")
        analysis = Analysis(video=video, transcript=transcript)
        set_project(project, progress=98, message="正在写入字幕分析文件")
        write_json(workdir / "transcript.json", [to_plain(item) for item in transcript])
        write_json(workdir / "analysis.json", to_plain(analysis))
        set_project(
            project,
            stage="素材分析",
            status="draft",
            active_task="",
            progress=100,
            message=f"字幕提取完成，已识别 {len(transcript)} 段",
            error=None,
        )
    except Exception as exc:
        fail_project(project, exc)


def transcribe_audio_isolated(
    audio_path: Path,
    workdir: Path,
    project: ProjectState,
    progress_callback: Any,
) -> list[TranscriptSegment]:
    output_path = workdir / "transcript_worker.json"
    log_path = workdir / "transcribe_worker.log"
    config_path = create_app_config_path()
    cmd = [
        sys.executable,
        "-m",
        "video_commentary.transcribe_worker",
        "--audio",
        str(audio_path),
        "--output",
        str(output_path),
    ]
    if config_path:
        cmd.extend(["--config", config_path])

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["VIDEO_COMMENTARY_TRANSCRIBE_CHECKPOINT"] = str(output_path)
    process = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    logs: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        text = line.strip()
        if not text:
            continue
        logs.append(text)
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            append_debug(project, "worker", text)
            save_project(project)
            continue
        if event.get("type") == "progress":
            progress_callback(float(event.get("ratio", 0)), str(event.get("message", "")))
        elif event.get("type") == "done":
            append_debug(project, "worker", f"转写子进程完成，段落数 {event.get('segments')}")
            save_project(project)
        elif event.get("type") == "error":
            append_debug(project, "worker-error", str(event.get("message", "")))
            save_project(project)
    returncode = process.wait()
    log_path.write_text("\n".join(logs), encoding="utf-8")
    if output_path.exists():
        data = read_json(output_path)
        segments = [
            TranscriptSegment(
                start=float(item["start"]),
                end=float(item["end"]),
                text=str(item["text"]),
                role=str(item.get("role", "")),
            )
            for item in data
        ]
        if returncode != 0:
            append_debug(project, "worker", f"转写子进程退出码 {returncode}，已使用 checkpoint 中的 {len(segments)} 段字幕继续")
            save_project(project)
        return segments
    if returncode != 0:
        raise RuntimeError(f"字幕转写子进程失败，退出码 {returncode}。日志: {log_path}")
    return []


def run_script_project(project_id: str) -> None:
    project = require_project(project_id)
    cfg = project_config(project)
    workdir = Path(project.workdir)
    try:
        set_project(project, progress=15, message="读取字幕与视频分析结果")
        from .models import analysis_from_dict

        analysis = analysis_from_dict(read_json(workdir / "analysis.json"))
        set_project(project, progress=38, message="根据字幕和节奏选择片段")
        plan = build_plan(analysis, cfg, project.target_minutes, project.narration_ratio)
        write_json(workdir / "plan.json", to_plain(plan))
        set_project(project, progress=64, message="正在让大模型生成自然解说稿")
        script = generate_script(plan, cfg)
        write_json(workdir / "script.json", to_plain(script))
        set_project(
            project,
            stage="文案审核",
            status="draft",
            active_task="",
            progress=100,
            message="文案已生成，可审核修改后进入配音",
            error=None,
        )
    except Exception as exc:
        fail_project(project, exc)


def run_voice_project(project_id: str) -> None:
    project = require_project(project_id)
    cfg = project_config(project)
    workdir = Path(project.workdir)
    try:
        script_path = workdir / "script.json"
        script = script_from_dict(read_json(script_path))
        if not script.lines:
            raise RuntimeError("文案为空，请先生成或编辑文案。")
        voice_dir = workdir / "voice"
        total = len(script.lines)
        for idx, line in enumerate(script.lines, start=1):
            set_project(project, progress=max(5, int((idx - 1) / total * 92)), message=f"正在生成第 {idx}/{total} 段旁白")
            one = Script(style=script.style, lines=[line])
            one = synthesize_voice(one, voice_dir, cfg)
            script.lines[idx - 1] = one.lines[0]
            write_json(script_path, to_plain(script))
        set_project(
            project,
            stage="配音审核",
            status="draft",
            active_task="",
            progress=100,
            message="旁白音频已生成，可逐段试听后导出",
            error=None,
        )
    except Exception as exc:
        fail_project(project, exc)


def run_render_project(project_id: str) -> None:
    project = require_project(project_id)
    cfg = project_config(project)
    workdir = Path(project.workdir)
    try:
        set_project(project, progress=20, message="读取选段、文案和旁白音频")
        plan = plan_from_dict(read_json(workdir / "plan.json"))
        script = script_from_dict(read_json(workdir / "script.json"))
        final_output = Path(project.output_path)
        temp_output = workdir / "render" / f"{final_output.stem}.tmp{final_output.suffix}"
        if temp_output.exists():
            temp_output.unlink()
        set_project(project, progress=55, message="正在混合原声与旁白并拼接视频")
        output = render_video(plan, script, temp_output, workdir, cfg)
        set_project(project, progress=92, message="正在写入最终视频文件")
        shutil.move(str(output), str(final_output))
        set_project(
            project,
            stage="完成",
            status="done",
            active_task="",
            progress=100,
            message="成片已生成",
            output_path=str(final_output),
            error=None,
        )
    except Exception as exc:
        fail_project(project, exc)


def friendly_error(exc: Exception) -> str:
    text = str(exc)
    if "cublas64_12.dll" in text:
        return (
            "CUDA 字幕识别失败：缺少 cublas64_12.dll。显卡已可见，但当前虚拟环境缺少 NVIDIA cuBLAS/cuDNN 运行库。"
            "请安装 nvidia-cublas-cu12 和 nvidia-cudnn-cu12，或临时把 WHISPER_DEVICE 改回 cpu。"
        )
    if "usage limit exceeded" in text.lower():
        return "MiniMax 配音失败：接口返回 usage limit exceeded，通常是账号额度不足、达到限流或套餐不支持当前 TTS 模型。请检查 MiniMax 控制台额度，或换用可用的 TTS_MODEL/TTS_VOICE 后重试。"
    return text


def gpu_status() -> dict[str, Any]:
    query = "name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        line = result.stdout.strip().splitlines()[0]
        name, util, mem_used, mem_total, temp, power = [part.strip() for part in line.split(",")]
        apps = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        processes = []
        for row in apps.stdout.strip().splitlines():
            parts = [part.strip() for part in row.split(",")]
            if len(parts) >= 3:
                processes.append({"pid": parts[0], "name": parts[1], "memory_mb": parts[2]})
        return {
            "ok": True,
            "name": name,
            "utilization": int(float(util)),
            "memory_used_mb": int(float(mem_used)),
            "memory_total_mb": int(float(mem_total)),
            "temperature_c": int(float(temp)),
            "power_w": float(power) if power not in {"[Not Supported]", "N/A"} else None,
            "processes": processes,
        }
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


def fail_project(project: ProjectState, exc: Exception) -> None:
    message = friendly_error(exc)
    append_debug(project, "error", message)
    append_debug(project, "traceback", traceback.format_exc())
    set_project(project, status="failed", active_task="", progress=100, error=message, message=message)


def append_debug(project: ProjectState, level: str, message: str) -> None:
    if not message:
        return
    project.debug_events.append(
        {
            "time": time.strftime("%H:%M:%S", time.localtime()),
            "level": level,
            "message": str(message),
        }
    )
    project.debug_events = project.debug_events[-120:]


def default_style_prompt() -> str:
    return (
        "中文励志电影解说风格。像《士兵突击》的不抛弃不放弃、《阿甘正传》的朴素坚持、"
        "《死亡诗社》的自我觉醒。语言要有画面感、节制、坚定，不要鸡汤堆砌，不要剧透式流水账。"
    )


def project_config(project: ProjectState) -> dict[str, Any]:
    cfg = load_config(create_app_config_path())
    cfg["target_minutes"] = project.target_minutes
    cfg["narration_ratio"] = project.narration_ratio
    cfg["style"]["protagonist"] = project.protagonist
    cfg["style"]["perspective"] = project.narrative_perspective
    cfg["style"]["name"] = project.style_name
    cfg["style"]["prompt"] = project.style_prompt or default_style_prompt()
    if project.llm_base_url:
        cfg["llm"]["base_url"] = project.llm_base_url
    if project.llm_model:
        cfg["llm"]["model"] = project.llm_model
    if project.tts_provider:
        cfg["tts_provider"] = project.tts_provider
    if project.tts_base_url:
        cfg["tts"]["base_url"] = project.tts_base_url
    if project.tts_model:
        cfg["tts"]["model"] = project.tts_model
    if project.tts_voice:
        cfg["tts"]["voice"] = project.tts_voice
    if project.transcribe_provider:
        cfg["transcribe"]["provider"] = project.transcribe_provider
    if project.whisper_model:
        cfg["transcribe"]["local_model"] = project.whisper_model
    if project.whisper_beam_size:
        cfg["transcribe"]["beam_size"] = int(project.whisper_beam_size)
        cfg["transcribe"]["best_of"] = int(project.whisper_beam_size)
    if project.whisper_initial_prompt:
        cfg["transcribe"]["initial_prompt"] = project.whisper_initial_prompt
    return cfg


def update_project_options(project: ProjectState, payload: dict[str, Any]) -> None:
    for key in (
        "target_minutes",
        "narration_ratio",
        "protagonist",
        "narrative_perspective",
        "style_name",
        "style_prompt",
        "llm_provider",
        "llm_base_url",
        "llm_model",
        "tts_provider",
        "tts_base_url",
        "tts_model",
        "tts_voice",
        "transcribe_provider",
        "whisper_model",
        "whisper_beam_size",
        "whisper_initial_prompt",
    ):
        if key in payload:
            current = getattr(project, key)
            if isinstance(current, float):
                setattr(project, key, float(payload[key]))
            else:
                setattr(project, key, str(payload[key]))
    save_project(project)


def project_path(project_id: str) -> Path:
    return PROJECTS_ROOT / project_id / "project.json"


def load_project(project_id: str) -> ProjectState | None:
    path = project_path(project_id)
    if not path.exists():
        return None
    data = read_json(path)
    data.setdefault("subtitle_path", "")
    data.setdefault("progress", 0)
    data.setdefault("active_task", "")
    data.setdefault("debug_events", [])
    data.setdefault("protagonist", "")
    data.setdefault("narrative_perspective", "third")
    data.setdefault("transcribe_provider", "")
    data.setdefault("whisper_model", "")
    data.setdefault("whisper_beam_size", 5)
    data.setdefault("whisper_initial_prompt", "")
    project = ProjectState(**data)
    return mark_stale_running(project)


def require_project(project_id: str) -> ProjectState:
    project = load_project(project_id)
    if project is None:
        raise RuntimeError("项目不存在")
    return project


def load_all_projects() -> list[ProjectState]:
    if not PROJECTS_ROOT.exists():
        return []
    projects = []
    for path in PROJECTS_ROOT.glob("*/project.json"):
        try:
            data = read_json(path)
            data.setdefault("subtitle_path", "")
            data.setdefault("progress", 0)
            data.setdefault("active_task", "")
            data.setdefault("debug_events", [])
            data.setdefault("protagonist", "")
            data.setdefault("narrative_perspective", "third")
            data.setdefault("transcribe_provider", "")
            data.setdefault("whisper_model", "")
            data.setdefault("whisper_beam_size", 5)
            data.setdefault("whisper_initial_prompt", "")
            projects.append(mark_stale_running(ProjectState(**data)))
        except Exception:
            continue
    return projects


def save_project(project: ProjectState) -> None:
    project.updated_at = time.time()
    write_json(project_path(project.id), asdict(project))


def mark_stale_running(project: ProjectState) -> ProjectState:
    output = Path(project.output_path)
    output_is_new = False
    if output.exists() and output.stat().st_size > 0:
        output_is_new = output.stat().st_mtime >= float(project.updated_at or 0)
    if project.status == "running" and project.active_task == "render" and output_is_new:
        project.status = "done"
        project.stage = "完成"
        project.active_task = ""
        project.progress = 100
        project.error = None
        project.message = "成片已生成"
        append_debug(project, "done", project.message)
        save_project(project)
        return project
    if project.status == "running" and time.time() - float(project.updated_at or 0) > 600:
        message = "任务长时间没有进度更新，可能是后端服务已停止或转写进程异常退出。请查看调试日志后重新执行该步骤。"
        project.status = "failed"
        project.active_task = ""
        project.progress = 100
        project.error = message
        project.message = message
        append_debug(project, "error", message)
        save_project(project)
    return project


def save_subtitle_file(subtitle_file: Any, workdir: Path) -> Path | None:
    if not subtitle_file or not getattr(subtitle_file, "filename", ""):
        return None
    suffix = Path(secure_filename(subtitle_file.filename)).suffix.lower()
    if suffix not in {".srt", ".vtt", ".ass", ".ssa"}:
        return None
    target = workdir / f"subtitle{suffix}"
    subtitle_file.save(target)
    if suffix != ".srt":
        return target
    return target


def set_project(project: ProjectState, **updates: Any) -> None:
    for key, value in updates.items():
        setattr(project, key, value)
    if "message" in updates and updates.get("message"):
        append_debug(project, str(updates.get("status") or "info"), str(updates["message"]))
    if "error" in updates and updates.get("error"):
        append_debug(project, "error", str(updates["error"]))
    save_project(project)


def project_response(project: ProjectState) -> dict[str, Any]:
    data = asdict(project)
    data["created_label"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(project.created_at))
    data["updated_label"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(project.updated_at))
    data["artifacts"] = {}
    for name, path in artifact_paths(project).items():
        if path.exists():
            data["artifacts"][name] = url_for("get_artifact", project_id=project.id, name=name)
    data["analysis"] = safe_read(Path(project.workdir) / "analysis.json")
    data["plan"] = safe_read(Path(project.workdir) / "plan.json")
    data["script"] = safe_read(Path(project.workdir) / "script.json")
    if data["script"]:
        for line in data["script"].get("lines", []):
            voice_file = line.get("voice_file")
            if voice_file and Path(voice_file).exists():
                line["voice_url"] = url_for("get_voice", project_id=project.id, filename=Path(voice_file).name)
    return data


def safe_read(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return read_json(path)
    except Exception:
        return None


def artifact_paths(project: ProjectState) -> dict[str, Path]:
    workdir = Path(project.workdir)
    return {
        "output": Path(project.output_path),
        "analysis": workdir / "analysis.json",
        "plan": workdir / "plan.json",
        "script": workdir / "script.json",
        "subtitle": workdir / "subtitle_edited.srt",
    }


def write_srt(path: Path, segments: list[TranscriptSegment]) -> None:
    lines: list[str] = []
    for index, seg in enumerate(segments, start=1):
        lines.append(str(index))
        lines.append(f"{format_srt_time(seg.start)} --> {format_srt_time(seg.end)}")
        lines.append(f"{seg.role}: {seg.text}" if seg.role else seg.text)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def format_srt_time(seconds: float) -> str:
    ms_total = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(ms_total, 3600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def create_app_config_path() -> str | None:
    current = getattr(create_app, "_config_path", None)
    return current or (str(DEFAULT_CONFIG_PATH) if DEFAULT_CONFIG_PATH.exists() else None)


def main(config_path: str | None = None, host: str = "127.0.0.1", port: int = 7860) -> None:
    create_app._config_path = config_path  # type: ignore[attr-defined]
    WEB_ROOT.mkdir(parents=True, exist_ok=True)
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    app = create_app(config_path)
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
