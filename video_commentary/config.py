from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


DEFAULT_CONFIG: dict[str, Any] = {
    "target_minutes": 5,
    "narration_ratio": 0.45,
    "language": "zh",
    "workdir": ".runs",
    "models": {
        "transcript": "gpt-4o-mini-transcribe",
        "writer": "gpt-4.1-mini",
        "tts": "gpt-4o-mini-tts",
        "tts_voice": "marin",
    },
    "style": {
        "name": "motivational",
        "prompt": "中文励志电影解说风格，坚定、克制、有画面感。",
    },
    "selection": {
        "clip_min_seconds": 14,
        "clip_max_seconds": 42,
        "max_clips": 12,
        "context_padding_seconds": 2,
        "motivational_keyword_weight": 1.4,
        "dialogue_density_weight": 0.8,
        "even_coverage_weight": 0.35,
        "keywords": ["坚持", "努力", "希望", "梦想", "选择", "勇敢", "成长"],
    },
    "render": {
        "resolution": "1920x1080",
        "fps": 30,
        "video_bitrate": "6000k",
        "narration_volume": 1.0,
        "original_volume_under_narration": 0.28,
        "original_volume_without_narration": 0.78,
        "fade_seconds": 0.25,
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | None = None) -> dict[str, Any]:
    load_dotenv(override=True)
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if path:
        with Path(path).open("r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        cfg = deep_merge(cfg, loaded)
    minimax_api_key = os.getenv("MINIMAX_API_KEY", "")
    cfg["openai_api_key"] = os.getenv("OPENAI_API_KEY", "")
    cfg["llm"] = {
        "api_key": os.getenv("LLM_API_KEY") or minimax_api_key or os.getenv("OPENAI_API_KEY", ""),
        "base_url": os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
        "model": os.getenv("LLM_MODEL") or cfg.get("models", {}).get("writer", "gpt-4.1-mini"),
    }
    cfg["tts_provider"] = os.getenv("TTS_PROVIDER", "openai")
    cfg["tts"] = {
        "api_key": os.getenv("TTS_API_KEY") or minimax_api_key or os.getenv("OPENAI_API_KEY", ""),
        "base_url": os.getenv("TTS_BASE_URL", "https://api.openai.com/v1"),
        "model": os.getenv("TTS_MODEL") or cfg.get("models", {}).get("tts", "gpt-4o-mini-tts"),
        "voice": os.getenv("TTS_VOICE") or cfg.get("models", {}).get("tts_voice", "marin"),
        "minimax_group_id": os.getenv("MINIMAX_GROUP_ID", ""),
        "speed": os.getenv("TTS_SPEED", "1.0"),
        "volume": os.getenv("TTS_VOLUME", "1.0"),
        "pitch": os.getenv("TTS_PITCH", "0"),
    }
    cfg["image"] = {
        "api_key": os.getenv("IMAGE_API_KEY") or minimax_api_key or os.getenv("OPENAI_API_KEY", ""),
        "base_url": os.getenv("IMAGE_BASE_URL", "https://api.minimaxi.com/v1"),
        "model": os.getenv("IMAGE_MODEL", "image-01"),
    }
    cfg["video_generation"] = {
        "api_key": os.getenv("VIDEO_API_KEY") or minimax_api_key or os.getenv("OPENAI_API_KEY", ""),
        "base_url": os.getenv("VIDEO_BASE_URL", "https://api.minimaxi.com/v1"),
        "model": os.getenv("VIDEO_MODEL", "video-01"),
    }
    cfg["music"] = {
        "api_key": os.getenv("MUSIC_API_KEY") or minimax_api_key or os.getenv("OPENAI_API_KEY", ""),
        "base_url": os.getenv("MUSIC_BASE_URL", "https://api.minimaxi.com/v1"),
        "model": os.getenv("MUSIC_MODEL", "music-2.6"),
        "cover_model": os.getenv("MUSIC_COVER_MODEL", "music-cover"),
        "lyrics_model": os.getenv("LYRICS_MODEL", "lyrics_generation"),
    }
    return cfg


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def default_workdir(input_path: str, root: str) -> Path:
    stem = Path(input_path).stem.replace(" ", "_")
    return Path(root) / stem
