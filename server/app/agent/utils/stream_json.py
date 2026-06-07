"""
流式 JSON 字段提取器 — 从 LLM token 流中实时提取指定字段的字符串值。

用于在 LLM 流式生成 JSON 的同时，将目标字段的内容逐字符推送为 SSE delta 事件。
"""
import json
import re
from typing import AsyncGenerator, Callable, Awaitable


class _State:
    SEEK_KEY = 0
    IN_VALUE = 1
    COLLECT = 2
    DONE = 3


def _count_brace_delta(text: str) -> int:
    """统计 text 中未在字符串内的 { +1, } -1 的净值。"""
    delta = 0
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            delta += 1
        elif ch == "}":
            delta -= 1
    return delta


def _is_json_complete(text: str, initial_depth: int) -> bool:
    """检查 text 是否包含完整的 JSON 对象，从 initial_depth 开始跟踪括号。"""
    depth = initial_depth
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return True
    return False


async def stream_json_field(
    token_stream: AsyncGenerator,
    field_name: str,
    on_delta: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[list[dict], dict]:
    buffer = ""
    state = _State.SEEK_KEY
    stream_events: list[dict] = []
    escape_next = False
    brace_depth = 0
    full_json = ""  # 完整 JSON buffer，用于最终解析

    key_pattern = f'"{field_name}"'
    key_len = len(key_pattern)

    async for token in token_stream:
        if not token:
            continue
        buffer += token
        full_json += token

        if state == _State.SEEK_KEY:
            brace_depth += _count_brace_delta(token)
            idx = buffer.find(key_pattern)
            if idx >= 0:
                after_key = buffer[idx + key_len:]
                m = re.match(r'\s*:\s*"', after_key)
                if m:
                    value_start = idx + key_len + m.end()
                    buffer = buffer[value_start:]
                    state = _State.IN_VALUE
                    # 不 continue — 让 IN_VALUE 分支在同一次迭代中处理 buffer

        if state == _State.IN_VALUE:
            i = 0
            while i < len(buffer):
                ch = buffer[i]
                if escape_next:
                    stream_events.append({"type": "delta", "text": ch})
                    if on_delta:
                        await on_delta(ch)
                    escape_next = False
                    i += 1
                    continue
                if ch == "\\":
                    escape_next = True
                    i += 1
                    continue
                if ch == '"':
                    buffer = buffer[i + 1:]
                    state = _State.COLLECT
                    break
                stream_events.append({"type": "delta", "text": ch})
                if on_delta:
                    await on_delta(ch)
                i += 1

            if state == _State.IN_VALUE:
                buffer = ""

        if state == _State.COLLECT:
            if _is_json_complete(buffer, initial_depth=brace_depth):
                state = _State.DONE
                break

        if state == _State.DONE:
            break

    parsed: dict = _extract_json_dict(full_json)
    return stream_events, parsed


def _extract_json_dict(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}") + 1
    if start < 0 or end <= start:
        return {}
    json_str = text[start:end]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", json_str)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {}
