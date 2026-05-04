from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import base64
import json
import mimetypes
import uuid

from .ffmpeg import make_silence
from .models import Script
from .openai_http import OpenAIHTTPClient


def synthesize_voice(script: Script, out_dir: Path, cfg: dict[str, Any]) -> Script:
    out_dir.mkdir(parents=True, exist_ok=True)
    tts_cfg = cfg.get("tts", {})
    provider = str(cfg.get("tts_provider", "openai")).lower()
    api_key = tts_cfg.get("api_key") or cfg.get("openai_api_key")
    model = tts_cfg.get("model") or cfg.get("models", {}).get("tts", "gpt-4o-mini-tts")
    voice = tts_cfg.get("voice") or cfg.get("models", {}).get("tts_voice", "marin")
    compatible_providers = {"openai", "minimax", "openai-compatible", "ofox"}
    client = (
        OpenAIHTTPClient(api_key=api_key, base_url=tts_cfg.get("base_url", "https://api.openai.com/v1"))
        if api_key and provider in compatible_providers
        else None
    )
    if not api_key and not cfg.get("allow_silent_tts"):
        raise RuntimeError("未配置 TTS_API_KEY 或 OPENAI_API_KEY，无法生成真实旁白音频。")

    for line in script.lines:
        target = out_dir / f"narration_{line.clip_index:02d}.mp3"
        if provider in {"xiaomi", "mimo"} and api_key:
            target.write_bytes(xiaomi_mimo_tts(line.text, api_key, tts_cfg, model, voice))
        elif provider in {"minimax-official", "minimax_official"} and api_key:
            target.write_bytes(minimax_tts(line.text, api_key, tts_cfg, model, voice))
        elif client:
            audio = client.binary_post(
                "/audio/speech",
                {"model": model, "voice": voice, "input": line.text, "response_format": "mp3"},
            )
            target.write_bytes(audio)
        else:
            make_silence(line.target_seconds, target)
        line.voice_file = str(target)
    return script


def xiaomi_mimo_tts(text: str, api_key: str, tts_cfg: dict[str, Any], model: str, voice: str) -> bytes:
    base_url = str(tts_cfg.get("base_url") or "https://api.xiaomimimo.com/v1").rstrip("/")
    audio_format = str(tts_cfg.get("format") or "mp3").lower()
    style = str(tts_cfg.get("style") or "自然、清晰、沉稳的中文电影解说旁白。").strip()
    messages = []
    if style:
        messages.append({"role": "user", "content": style})
    messages.append({"role": "assistant", "content": text})
    payload = {
        "model": model or "mimo-v2.5-tts",
        "messages": messages,
        "modalities": ["audio"],
        "audio": {
            "voice": voice or "mimo_default",
            "format": audio_format,
        },
    }
    req = Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Xiaomi MiMo TTS 请求失败 {exc.code}: {detail}") from exc
    audio = extract_audio_bytes(data)
    if audio:
        return audio
    raise RuntimeError(f"Xiaomi MiMo TTS 未返回可识别的音频字段: {data}")


def extract_audio_bytes(data: Any) -> bytes | None:
    if isinstance(data, dict):
        for key in ("data", "audio", "b64_json", "base64", "content"):
            value = data.get(key)
            if isinstance(value, str):
                decoded = decode_audio_text(value)
                if decoded:
                    return decoded
            found = extract_audio_bytes(value)
            if found:
                return found
        for value in data.values():
            found = extract_audio_bytes(value)
            if found:
                return found
    if isinstance(data, list):
        for item in data:
            found = extract_audio_bytes(item)
            if found:
                return found
    return None


def decode_audio_text(value: str) -> bytes | None:
    text = value.strip()
    if not text:
        return None
    if text.startswith("data:audio"):
        text = text.split(",", 1)[-1]
    try:
        raw = base64.b64decode(text, validate=True)
        if raw.startswith((b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xe3", b"RIFF", b"OggS")) or len(raw) > 1000:
            return raw
    except Exception:
        pass
    try:
        raw = bytes.fromhex(text)
        if raw.startswith((b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xe3", b"RIFF", b"OggS")):
            return raw
    except Exception:
        pass
    return None


def minimax_tts(text: str, api_key: str, tts_cfg: dict[str, Any], model: str, voice: str) -> bytes:
    group_id = tts_cfg.get("minimax_group_id", "")
    base_url = str(tts_cfg.get("base_url") or "https://api.minimaxi.com/v1").rstrip("/")
    if group_id:
        url = f"https://api.minimax.chat/v1/t2a_v2?GroupId={group_id}"
    else:
        url = f"{base_url}/t2a_v2"
    payload = {
        "model": model or "speech-2.8-hd",
        "text": text,
        "stream": False,
        "language_boost": "Chinese",
        "output_format": "hex",
        "voice_setting": {
            "voice_id": voice or "male-qn-qingse",
            "speed": float(tts_cfg.get("speed", 1.0)),
            "vol": float(tts_cfg.get("volume", 1.0)),
            "pitch": int(tts_cfg.get("pitch", 0)),
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
    }
    req = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Minimax TTS 请求失败 {exc.code}: {detail}") from exc
    audio_hex = data.get("data", {}).get("audio") or data.get("audio")
    if not audio_hex:
        raise RuntimeError(f"Minimax TTS 未返回音频: {data}")
    return bytes.fromhex(audio_hex)


def minimax_clone_voice(audio_path: Path, api_key: str, base_url: str, voice_id: str) -> str:
    file_id = minimax_upload_file(audio_path, api_key, base_url)
    payload = {"file_id": file_id, "voice_id": voice_id}
    req = Request(
        f"{base_url.rstrip('/')}/voice_clone",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"MiniMax voice clone failed {exc.code}: {detail}") from exc
    base_resp = data.get("base_resp", {})
    if int(base_resp.get("status_code", 0)) != 0:
        raise RuntimeError(f"MiniMax voice clone failed: {base_resp}")
    return str(data.get("voice_id") or voice_id)


def minimax_upload_file(audio_path: Path, api_key: str, base_url: str) -> int:
    boundary = f"----codex-{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
    body = bytearray()
    for name, value in {"purpose": "voice_clone"}.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(f'Content-Disposition: form-data; name="file"; filename="{audio_path.name}"\r\n'.encode())
    body.extend(f"Content-Type: {content_type}\r\n\r\n".encode())
    body.extend(audio_path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    req = Request(
        f"{base_url.rstrip('/')}/files/upload",
        data=bytes(body),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"MiniMax upload failed {exc.code}: {detail}") from exc
    base_resp = data.get("base_resp", {})
    if int(base_resp.get("status_code", 0)) != 0:
        raise RuntimeError(f"MiniMax upload failed: {base_resp}")
    file_info = data.get("file") or {}
    return int(file_info.get("file_id") or data.get("file_id"))
