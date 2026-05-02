from __future__ import annotations

import time
import uuid
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from .cli import analyze_video
from .config import load_config, read_json, write_json
from .ffmpeg import FFmpegError, require_ffmpeg, resolve_exe
from .models import NarrationLine, Script, plan_from_dict, script_from_dict, to_plain
from .openai_http import OpenAIHTTPClient, chat_text, response_text
from .render import render_video
from .scriptgen import generate_script
from .selection import build_plan
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
    style_name: str = "soldiers_forest_gump_dead_poets"
    style_prompt: str = ""
    llm_provider: str = "openai-compatible"
    llm_base_url: str = ""
    llm_model: str = ""
    tts_provider: str = ""
    tts_base_url: str = ""
    tts_model: str = ""
    tts_voice: str = ""
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
                "tts_base_url": cfg.get("tts", {}).get("base_url", ""),
                "tts_provider": cfg.get("tts_provider", ""),
                "tts_model": cfg.get("tts", {}).get("model", ""),
                "tts_voice": cfg.get("tts", {}).get("voice", ""),
            }
        )

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
            return jsonify({"ok": False, "message": str(exc), "model": model}), 500

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
            style_prompt=default_style_prompt(),
            llm_base_url=cfg.get("llm", {}).get("base_url", ""),
            llm_model=cfg.get("llm", {}).get("model", ""),
            tts_provider=cfg.get("tts_provider", ""),
            tts_base_url=cfg.get("tts", {}).get("base_url", ""),
            tts_model=cfg.get("tts", {}).get("model", ""),
            tts_voice=cfg.get("tts", {}).get("voice", ""),
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
        cfg = project_config(project)
        try:
            set_project(project, stage="素材分析", status="running", message="正在提取音频并识别字幕", error=None)
            analysis = analyze_video(Path(project.input_path), Path(project.workdir), cfg)
            set_project(project, stage="素材分析", status="draft", message=f"已识别 {len(analysis.transcript)} 段字幕")
            return jsonify(project_response(project))
        except Exception as exc:
            set_project(project, status="failed", error=str(exc), message=str(exc))
            return jsonify(project_response(project)), 500

    @app.post("/api/projects/<project_id>/script")
    def generate_project_script(project_id: str):
        project = require_project(project_id)
        update_project_options(project, request.json or {})
        cfg = project_config(project)
        workdir = Path(project.workdir)
        try:
            analysis_path = workdir / "analysis.json"
            if not analysis_path.exists():
                analyze_video(Path(project.input_path), workdir, cfg)
            analysis = read_json(analysis_path)
            from .models import analysis_from_dict

            plan = build_plan(analysis_from_dict(analysis), cfg, project.target_minutes, project.narration_ratio)
            write_json(workdir / "plan.json", to_plain(plan))
            script = generate_script(plan, cfg)
            write_json(workdir / "script.json", to_plain(script))
            set_project(project, stage="文案审核", status="draft", message="文案已生成，可编辑后继续配音", error=None)
            return jsonify(project_response(project))
        except Exception as exc:
            set_project(project, status="failed", error=str(exc), message=str(exc))
            return jsonify(project_response(project)), 500

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
            )
            for item in payload.get("lines", [])
        ]
        script = Script(style=project.style_name, lines=lines)
        write_json(Path(project.workdir) / "script.json", to_plain(script))
        set_project(project, stage="文案审核", status="draft", message="文案已保存")
        return jsonify(project_response(project))

    @app.post("/api/projects/<project_id>/voice")
    def generate_project_voice(project_id: str):
        project = require_project(project_id)
        update_project_options(project, request.json or {})
        cfg = project_config(project)
        try:
            script_path = Path(project.workdir) / "script.json"
            if not script_path.exists():
                return jsonify({"error": "请先生成并保存文案"}), 400
            script = script_from_dict(read_json(script_path))
            script = synthesize_voice(script, Path(project.workdir) / "voice", cfg)
            write_json(script_path, to_plain(script))
            set_project(project, stage="配音审核", status="draft", message="旁白音频已生成，可试听后导出")
            return jsonify(project_response(project))
        except Exception as exc:
            set_project(project, status="failed", error=str(exc), message=str(exc))
            return jsonify(project_response(project)), 500

    @app.post("/api/projects/<project_id>/render")
    def render_project(project_id: str):
        project = require_project(project_id)
        cfg = project_config(project)
        workdir = Path(project.workdir)
        try:
            plan_path = workdir / "plan.json"
            script_path = workdir / "script.json"
            if not plan_path.exists() or not script_path.exists():
                return jsonify({"error": "缺少选段计划或文案"}), 400
            script = script_from_dict(read_json(script_path))
            missing_voice = [line.clip_index for line in script.lines if not line.voice_file or not Path(line.voice_file).exists()]
            if missing_voice:
                return jsonify({"error": f"这些段落还没有配音: {missing_voice[:8]}"}), 400
            set_project(project, stage="导出成片", status="running", message="正在混合原声与旁白并合成视频")
            output = render_video(plan_from_dict(read_json(plan_path)), script, Path(project.output_path), workdir, cfg)
            set_project(project, stage="完成", status="done", message="成片已生成", output_path=str(output), error=None)
            return jsonify(project_response(project))
        except Exception as exc:
            set_project(project, status="failed", error=str(exc), message=str(exc))
            return jsonify(project_response(project)), 500

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


def ffmpeg_ok() -> bool:
    try:
        require_ffmpeg()
        return True
    except FFmpegError:
        return False


def default_style_prompt() -> str:
    return (
        "中文励志电影解说风格。像《士兵突击》的不抛弃不放弃、《阿甘正传》的朴素坚持、"
        "《死亡诗社》的自我觉醒。语言要有画面感、节制、坚定，不要鸡汤堆砌，不要剧透式流水账。"
    )


def project_config(project: ProjectState) -> dict[str, Any]:
    cfg = load_config(create_app_config_path())
    cfg["target_minutes"] = project.target_minutes
    cfg["narration_ratio"] = project.narration_ratio
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
    return cfg


def update_project_options(project: ProjectState, payload: dict[str, Any]) -> None:
    for key in (
        "target_minutes",
        "narration_ratio",
        "style_name",
        "style_prompt",
        "llm_provider",
        "llm_base_url",
        "llm_model",
        "tts_provider",
        "tts_base_url",
        "tts_model",
        "tts_voice",
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
    return ProjectState(**data)


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
            projects.append(ProjectState(**data))
        except Exception:
            continue
    return projects


def save_project(project: ProjectState) -> None:
    project.updated_at = time.time()
    write_json(project_path(project.id), asdict(project))


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
    }


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
