from __future__ import annotations

import json
from typing import Any

from .models import NarrationLine, Plan, Script
from .openai_http import OpenAIHTTPClient, chat_text, response_text


def generate_script(plan: Plan, cfg: dict[str, Any]) -> Script:
    style = cfg.get("style", {})
    style_name = str(style.get("name", "motivational"))
    prompt = str(style.get("prompt", "中文电影解说风格，克制、有画面感，避免空泛鸡汤。"))
    llm_cfg = cfg.get("llm", {})
    api_key = llm_cfg.get("api_key") or cfg.get("openai_api_key")
    if not api_key:
        return fallback_script(plan, style_name)

    client = OpenAIHTTPClient(api_key=api_key, base_url=llm_cfg.get("base_url", "https://api.openai.com/v1"))
    model = llm_cfg.get("model") or cfg.get("models", {}).get("writer", "gpt-4.1-mini")
    payload = {
        "target_total_seconds": round(plan.target_duration, 1),
        "narration_ratio": plan.narration_ratio,
        "clips": [
            {
                "clip_index": clip.index,
                "source_start": round(clip.source_start, 1),
                "source_end": round(clip.source_end, 1),
                "duration": round(clip.duration, 1),
                "target_narration_seconds": round(clip.narration_target_seconds, 1),
                "subtitle_or_dialogue": clip.transcript[:1600],
            }
            for clip in plan.clips
        ],
    }
    instructions = f"""
你是中文视频解说编剧，正在为一个由原片剪出的短视频写旁白。
风格要求：{prompt}

必须遵守：
1. 只输出 JSON，格式为 {{"lines":[{{"clip_index":1,"text":"...","target_seconds":12.0}}]}}。
2. 每个 clip_index 必须且只能有一条旁白。
3. 旁白必须贴合 clip 的 source_start/source_end 时间段和 subtitle_or_dialogue，不要写与该片段无关的泛泛励志句。
4. 如果 subtitle_or_dialogue 为空，说明当前项目没有字幕或转写；只能写桥接式旁白，不要编造角色、剧情、地点或具体动作。
5. 不要复述字幕原文，要提炼冲突、转折、选择、情绪变化，并给出适合插入原片空隙的短句。
6. 控制字数：普通话约每秒 3.5 到 4 个汉字，按 target_narration_seconds 写。
7. 各段内容要有差异，避免重复句式。
""".strip()

    user_input = json.dumps(payload, ensure_ascii=False)
    if "api.openai.com" in str(llm_cfg.get("base_url", "")):
        response = client.json_post(
            "/responses",
            {
                "model": model,
                "instructions": instructions,
                "input": user_input,
            },
        )
        text = response_text(response)
    else:
        response = client.json_post(
            "/chat/completions",
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": user_input},
                ],
                "temperature": 0.7,
            },
        )
        text = chat_text(response)
    try:
        data = parse_json_object(text)
    except Exception:
        return fallback_script(plan, style_name)
    lines = [
        NarrationLine(
            clip_index=int(item["clip_index"]),
            text=str(item.get("text", "")).strip(),
            target_seconds=float(item.get("target_seconds", 0)),
        )
        for item in data.get("lines", [])
        if str(item.get("text", "")).strip()
    ]
    if len(lines) != len(plan.clips):
        return fallback_script(plan, style_name)
    return Script(style=style_name, lines=lines)


def fallback_script(plan: Plan, style_name: str) -> Script:
    lines = []
    for clip in plan.clips:
        if clip.transcript:
            base = clip.transcript.strip().replace("\n", " ")
            text = (
                "这一段真正值得保留的，不只是台词本身，而是它背后的选择。"
                f"{base[:80]} 之后，情绪开始往前推，观众需要在这里听见人物为什么继续。"
            )
        else:
            start_min = int(clip.source_start // 60)
            start_sec = int(clip.source_start % 60)
            text = (
                f"原片来到 {start_min}分{start_sec:02d}秒，这里更适合留出画面呼吸。"
                "旁白只做轻轻推进，把观众带向下一次选择。"
            )
        lines.append(NarrationLine(clip_index=clip.index, text=text, target_seconds=clip.narration_target_seconds))
    return Script(style=style_name, lines=lines)


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        stripped = stripped[start : end + 1]
    return json.loads(stripped)
