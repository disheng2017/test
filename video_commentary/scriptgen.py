from __future__ import annotations

import json
from typing import Any

from .models import NarrationLine, Plan, Script
from .openai_http import OpenAIHTTPClient, chat_text, response_text


def generate_script(plan: Plan, cfg: dict[str, Any]) -> Script:
    style = cfg.get("style", {})
    style_name = str(style.get("name", "motivational"))
    prompt = str(style.get("prompt", "中文电影解说风格，克制、有画面感，避免空泛鸡汤。"))
    protagonist = str(style.get("protagonist", "")).strip()
    perspective = str(style.get("perspective", "third")).strip().lower()
    llm_cfg = cfg.get("llm", {})
    api_key = llm_cfg.get("api_key") or cfg.get("openai_api_key")
    if not api_key:
        return fallback_script(plan, style_name)

    client = OpenAIHTTPClient(api_key=api_key, base_url=llm_cfg.get("base_url", "https://api.openai.com/v1"))
    model = llm_cfg.get("model") or cfg.get("models", {}).get("writer", "gpt-4.1-mini")
    payload = {
        "target_total_seconds": round(plan.target_duration, 1),
        "narration_ratio": plan.narration_ratio,
        "protagonist": protagonist,
        "perspective": perspective,
        "clips": [
            {
                "clip_index": clip.index,
                "source_start": round(clip.source_start, 1),
                "source_end": round(clip.source_end, 1),
                "duration": round(clip.duration, 1),
                "target_narration_seconds": round(clip.narration_target_seconds, 1),
                "subtitle_or_dialogue": clip.transcript[:2200],
            }
            for clip in plan.clips
        ],
    }
    protagonist_rule = (
        f"主叙事视角围绕主人公“{protagonist}”：解释他/她在这个精彩节点里的困境、念头、选择和变化。"
        if protagonist
        else "如果能从字幕判断主人公，请把旁白主线集中在主人公的困境、念头、选择和变化上。"
    )
    perspective_rule = (
        "使用第一人称视角，用“我/我们”的代入式表达写主人公感受，但不要装成角色原台词。"
        if perspective == "first"
        else "使用第三人称视角，用“他/她/这个人”的客观叙述表达，不要频繁使用“我”。"
    )
    instructions = f"""
你是中文视频解说编剧，正在为原片精选片段写少量重点旁白。风格要求：{prompt}

必须遵守：
1. 只输出 JSON，格式为 {{"lines":[{{"clip_index":1,"text":"...","target_seconds":28.0}}]}}。
2. 总共写 2 到 3 段旁白即可；不要把每个小情绪都拆开讲。
3. 每段旁白要稍微长一些，像在精彩处插入一段有深度、有趣、带观点的解说，而不是碎片化短句。
4. {protagonist_rule}
5. {perspective_rule}
6. 每段只能对应一个 clip_index，优先选择最有冲突、转折、误会、选择或人物变化的片段。
7. 不要逐字复述字幕原文，要讲出对白背后的情绪、关系、压力和荒诞感。
8. 允许有一点幽默或犀利观察，但不要油腻、不要鸡汤、不要喊口号。
9. 必须贴合对应 clip 的时间段和 subtitle_or_dialogue；没有依据时不要编造剧情。
10. 控制字数：普通话约每秒 3.2 到 3.8 个汉字。每段建议 20 到 40 秒，让原片对白和环境声有呼吸。
11. 多留原声空间，旁白像精准插针，不要全程铺满。
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
                "temperature": 0.75,
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
            target_seconds=max(18.0, float(item.get("target_seconds", 0))),
        )
        for item in data.get("lines", [])
        if str(item.get("text", "")).strip()
    ]
    valid_clip_ids = {clip.index for clip in plan.clips}
    deduped: list[NarrationLine] = []
    seen: set[int] = set()
    for line in lines:
        if line.clip_index not in valid_clip_ids or line.clip_index in seen:
            continue
        seen.add(line.clip_index)
        deduped.append(line)
    if not 1 <= len(deduped) <= min(3, len(plan.clips)):
        return fallback_script(plan, style_name)
    return Script(style=style_name, lines=deduped[:3])


def fallback_script(plan: Plan, style_name: str) -> Script:
    lines = []
    selected = sorted(plan.clips, key=lambda clip: clip.score, reverse=True)[: min(3, len(plan.clips))]
    for clip in sorted(selected, key=lambda item: item.source_start):
        if clip.transcript:
            base = clip.transcript.strip().replace("\n", " ")
            text = (
                f"这一段好看的地方，不在于谁说赢了谁，而是人物终于露出了真实的压力。{base[:80]} "
                "台词表面很轻，背后其实是在试探底线：他到底还能忍多久，又愿不愿意承认自己已经被推到了选择面前。"
            )
        else:
            start_min = int(clip.source_start // 60)
            start_sec = int(clip.source_start % 60)
            text = (
                f"画面来到 {start_min}分{start_sec:02d}秒，这里不用急着解释太满。"
                "真正有意思的是沉默里的变化：人还站在原地，心里的方向已经开始偏了。"
            )
        lines.append(
            NarrationLine(
                clip_index=clip.index,
                text=text,
                target_seconds=max(20.0, clip.narration_target_seconds),
            )
        )
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
