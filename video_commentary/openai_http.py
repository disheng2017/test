from __future__ import annotations

import json
import mimetypes
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class OpenAIHTTPError(RuntimeError):
    pass


class OpenAIHTTPClient:
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1") -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY 未配置")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def json_post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = Request(
            self.base_url + path,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        return json.loads(self._open(req).decode("utf-8"))

    def binary_post(self, path: str, payload: dict[str, Any]) -> bytes:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = Request(
            self.base_url + path,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        return self._open(req)

    def multipart_post(self, path: str, fields: dict[str, Any], files: dict[str, Path]) -> dict[str, Any]:
        boundary = f"----codex-{uuid.uuid4().hex}"
        body = bytearray()
        for name, value in fields.items():
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")
        for name, file_path in files.items():
            content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(
                f'Content-Disposition: form-data; name="{name}"; filename="{file_path.name}"\r\n'.encode()
            )
            body.extend(f"Content-Type: {content_type}\r\n\r\n".encode())
            body.extend(file_path.read_bytes())
            body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())

        req = Request(
            self.base_url + path,
            data=bytes(body),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        return json.loads(self._open(req).decode("utf-8"))

    def _open(self, req: Request) -> bytes:
        try:
            with urlopen(req, timeout=180) as resp:
                return resp.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise OpenAIHTTPError(f"OpenAI API 请求失败 {exc.code}: {detail}") from exc


def response_text(data: dict[str, Any]) -> str:
    if "output_text" in data:
        return str(data["output_text"])
    chunks: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"}:
                chunks.append(str(content.get("text", "")))
    return "\n".join(part for part in chunks if part)


def chat_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content", "")
    if isinstance(content, list):
        return strip_thinking("".join(str(item.get("text", "")) for item in content if isinstance(item, dict)))
    return strip_thinking(str(content))


def strip_thinking(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<think>.*$", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()
