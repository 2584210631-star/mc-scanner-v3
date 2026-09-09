# -*- coding: utf-8 -*-
"""
AI 内容生成模块。
支持 OpenAI 兼容 API，可生成小说故事、名人简介、自定义主题文本。
生成长文本自动按 MC 聊天长度限制（256字符）分段。
"""
import json
import urllib.request
import urllib.error
from typing import Optional


# 预设生成模板
PRESETS = {
    "novel": {
        "label": "小说故事",
        "system": "你是一位擅长短篇故事创作的作家，写的故事引人入胜、情节紧凑。",
        "template": "请以「{topic}」为主题，写一篇300字左右的短篇故事，要求有开头、发展、结尾，语言生动。",
    },
    "celebrity": {
        "label": "名人简介",
        "system": "你是一位知识渊博的传记作家，擅长用简洁生动的语言介绍名人。",
        "template": "请介绍名人「{topic}」的生平、主要成就和历史影响，300字左右，语言通俗易懂。",
    },
    "poem": {
        "label": "诗词",
        "system": "你是一位诗人，擅长创作各种风格的诗歌。",
        "template": "请以「{topic}」为主题创作一首诗，风格不限，要求意境优美。",
    },
    "speech": {
        "label": "演讲稿",
        "system": "你是一位演讲撰稿人，擅长写有感染力的演讲稿。",
        "template": "请以「{topic}」为主题写一篇简短的演讲稿，300字左右，有号召力。",
    },
    "joke": {
        "label": "笑话段子",
        "system": "你是一位幽默大师，擅长讲各种笑话。",
        "template": "请讲一个关于「{topic}」的笑话，要简短好笑。",
    },
    "custom": {
        "label": "自定义",
        "system": "你是一个 helpful 的助手。",
        "template": "{topic}",
    },
}

# MC 聊天单条最大长度（留余量）
MC_CHAT_MAX = 240


def split_for_minecraft(text: str, max_len: int = MC_CHAT_MAX) -> list:
    """把长文本按 MC 聊天长度限制分段，尽量在句号/换行处断开。"""
    lines = text.replace("\r\n", "\n").split("\n")
    result = []
    current = ""
    for line in lines:
        line = line.strip()
        if not line:
            if current:
                result.append(current)
                current = ""
            continue
        # 按句子分割
        sentences = []
        buf = ""
        for ch in line:
            buf += ch
            if ch in "。！？!?；;":
                sentences.append(buf)
                buf = ""
        if buf:
            sentences.append(buf)
        for s in sentences:
            if len(current) + len(s) + 1 <= max_len:
                current += s
            else:
                if current:
                    result.append(current)
                # 单句超长，硬切
                while len(s) > max_len:
                    result.append(s[:max_len])
                    s = s[max_len:]
                current = s
    if current:
        result.append(current)
    return [r for r in result if r.strip()]


def generate_content(
    topic: str,
    preset: str = "novel",
    api_key: str = "",
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-3.5-turbo",
    custom_prompt: Optional[str] = None,
    custom_system: Optional[str] = None,
    timeout: int = 60,
) -> dict:
    """
    调用 AI 生成内容。
    返回: {"success": bool, "text": str, "segments": list, "error": str}
    """
    if not api_key:
        return {"success": False, "text": "", "segments": [], "error": "未配置 API Key，请在设置中填写 ai_api_key"}

    preset_cfg = PRESETS.get(preset, PRESETS["custom"])
    system = custom_system or preset_cfg["system"]
    if custom_prompt:
        user_prompt = custom_prompt
    else:
        user_prompt = preset_cfg["template"].format(topic=topic)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.8,
        "max_tokens": 1024,
    }

    url = base_url.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"].strip()
        segments = split_for_minecraft(text)
        return {"success": True, "text": text, "segments": segments, "error": ""}
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = str(e)
        return {"success": False, "text": "", "segments": [], "error": f"HTTP {e.code}: {err_body[:200]}"}
    except Exception as e:
        return {"success": False, "text": "", "segments": [], "error": str(e)}


def get_preset_list() -> list:
    """返回预设列表，供前端下拉选择。"""
    return [{"key": k, "label": v["label"]} for k, v in PRESETS.items()]
