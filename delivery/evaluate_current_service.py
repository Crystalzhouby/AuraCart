#!/usr/bin/env python3
"""Evaluate the local AuraCart service against delivery/评测集.md.

The script extracts single-turn and multi-turn cases from the markdown file,
calls the local SSE API, and writes both raw JSON and a readable markdown report.
It intentionally does not assign pass/fail labels automatically; the generated
report is meant to support quick human scoring against the reference answers.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


@dataclass
class Case:
    case_id: str
    group: str
    subgroup: str
    turns: list[str]
    reference: str


def _strip_prefix(line: str, prefix: str) -> str:
    return line.split(prefix, 1)[1].strip()


def parse_cases(path: Path) -> list[Case]:
    cases: list[Case] = []
    group = ""
    subgroup = ""
    pending_question: str | None = None
    pending_turns: list[str] | None = None
    case_no = 1

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("## ") and stripped != "## 使用方法":
            group = stripped[3:].strip()
            subgroup = ""
            continue
        if stripped.startswith("### "):
            subgroup = stripped[4:].strip()
            continue

        if stripped.startswith("- 用户问题："):
            pending_question = _strip_prefix(stripped, "- 用户问题：")
            pending_turns = None
            continue

        if stripped.startswith("- 测试步骤："):
            pending_question = None
            pending_turns = []
            continue

        if pending_turns is not None:
            match = re.match(r"\d+\.\s*输入：(.+)$", stripped)
            if match:
                pending_turns.append(match.group(1).strip())
                continue

        if stripped.startswith("参考回答：") or stripped.startswith("- 参考回答："):
            prefix = "参考回答：" if stripped.startswith("参考回答：") else "- 参考回答："
            reference = _strip_prefix(stripped, prefix)
            if pending_question:
                turns = [pending_question]
            elif pending_turns:
                turns = pending_turns
            else:
                continue
            cases.append(
                Case(
                    case_id=f"C{case_no:03d}",
                    group=group,
                    subgroup=subgroup,
                    turns=turns,
                    reference=reference,
                )
            )
            case_no += 1
            pending_question = None
            pending_turns = None

    return cases


def http_json(url: str, timeout: float) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def create_conversation(base_url: str, timeout: float) -> str:
    data = http_json(f"{base_url}/api/conversation", timeout)
    return data["conversation_id"]


def parse_sse(url: str, timeout: float) -> tuple[list[dict[str, Any]], bool]:
    """Read SSE stream until a ``done`` event is received.

    The ``done`` event is the **only** successful termination condition.
    Timeout or a clean EOF from the peer both count as abnormal; the caller
    should mark the turn as incomplete.

    Returns ``(events, completed_via_done)``.
    """
    req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
    events: list[dict[str, Any]] = []
    started = time.time()
    completed_via_done = False
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        current_event = "message"
        data_lines: list[str] = []
        while True:
            if time.time() - started > timeout:
                events.append({"event": "client_timeout", "data": {"timeout_s": timeout}})
                # flush any pending buffer so the last partial event isn't lost
                if data_lines:
                    data_raw = "\n".join(data_lines)
                    try:
                        data: Any = json.loads(data_raw)
                    except json.JSONDecodeError:
                        data = data_raw
                    events.append({"event": current_event, "data": data})
                break
            line_b = resp.readline()
            if not line_b:
                # peer closed the connection without sending ``done``
                if data_lines:
                    data_raw = "\n".join(data_lines)
                    try:
                        data = json.loads(data_raw)
                    except json.JSONDecodeError:
                        data = data_raw
                    events.append({"event": current_event, "data": data})
                break
            line = line_b.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line:
                if data_lines:
                    data_raw = "\n".join(data_lines)
                    try:
                        data = json.loads(data_raw)
                    except json.JSONDecodeError:
                        data = data_raw
                    events.append({"event": current_event, "data": data})
                    if current_event == "done":
                        completed_via_done = True
                        break
                current_event = "message"
                data_lines = []
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                current_event = line.split(":", 1)[1].strip()
                continue
            if line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
                continue
    return events, completed_via_done


def fetch_products(base_url: str, ids: list[str], timeout: float) -> dict[str, Any]:
    if not ids:
        return {}
    query = urllib.parse.urlencode({"ids": ",".join(ids)})
    try:
        data = http_json(f"{base_url}/api/products/batch?{query}", timeout)
    except Exception:
        return {}
    return {row["product_id"]: row for row in data}


def summarize_events(events: list[dict[str, Any]]) -> tuple[str, list[str], list[str]]:
    text_parts: list[str] = []
    product_ids: list[str] = []
    errors: list[str] = []

    for item in events:
        event = item.get("event")
        data = item.get("data")
        if event in {"welcome", "chat_reply", "category_intro", "product_reason", "ending"}:
            if isinstance(data, str) and data.strip():
                text_parts.append(data.strip())
        elif event in {"welcome_chat_stream", "category_intro_stream", "ending_stream"}:
            if isinstance(data, dict) and data.get("type") == "delta":
                text = data.get("text", "")
                if text:
                    text_parts.append(text)
        elif event == "products":
            if isinstance(data, dict) and data.get("product_id"):
                pid = str(data["product_id"])
                if pid not in product_ids:
                    product_ids.append(pid)
        elif event == "error":
            errors.append(json.dumps(data, ensure_ascii=False))

    combined = "".join(text_parts)
    return combined, product_ids, errors


def evaluate_case(case: Case, base_url: str, turn_timeout: float) -> dict[str, Any]:
    conversation_id = create_conversation(base_url, turn_timeout)
    turn_results: list[dict[str, Any]] = []
    all_product_ids: list[str] = []
    has_incomplete_turn = False
    for turn in case.turns:
        query = urllib.parse.urlencode({"q": turn, "stream": "false"})
        url = f"{base_url}/api/search/{conversation_id}?{query}"
        started = time.time()
        try:
            events, completed_via_done = parse_sse(url, turn_timeout)
            error = None
        except Exception as exc:
            events = []
            completed_via_done = False
            error = repr(exc)
        elapsed = round(time.time() - started, 2)
        answer, product_ids, errors = summarize_events(events)
        if not completed_via_done:
            errors.append("未收到 done 事件（服务端提前断开或超时）")
            has_incomplete_turn = True
        for pid in product_ids:
            if pid not in all_product_ids:
                all_product_ids.append(pid)
        turn_results.append(
            {
                "query": turn,
                "elapsed_s": elapsed,
                "answer": answer,
                "product_ids": product_ids,
                "errors": errors,
                "client_error": error,
                "events": events,
                "completed_via_done": completed_via_done,
            }
        )
    products = fetch_products(base_url, all_product_ids, turn_timeout)
    return {
        **asdict(case),
        "conversation_id": conversation_id,
        "has_incomplete_turn": has_incomplete_turn,
        "turn_results": turn_results,
        "products": products,
    }


def render_markdown(results: list[dict[str, Any]], base_url: str) -> str:
    lines = [
        "# 当前服务评测原始结果",
        "",
        f"- 服务地址：`{base_url}`",
        f"- 生成时间：`{time.strftime('%Y-%m-%d %H:%M:%S')}`",
        f"- 用例数量：`{len(results)}`",
        "- 评分栏为人工复核预留：通过 / 部分通过 / 不通过。",
        "",
    ]
    for result in results:
        status_bits = []
        if result.get("has_incomplete_turn"):
            status_bits.append("⚠️ 存在未收到 done 的轮次")
        status_line = f"- 评分：待复核{' | ' + '，'.join(status_bits) if status_bits else ''}"
        lines.extend(
            [
                f"## {result['case_id']} {result['group']} / {result['subgroup']}",
                "",
                status_line,
                f"- 会话：`{result['conversation_id']}`",
                f"- 参考回答：{result['reference']}",
                "",
            ]
        )
        for idx, turn in enumerate(result["turn_results"], 1):
            products = [
                result["products"].get(pid, {"product_id": pid})
                for pid in turn["product_ids"]
            ]
            product_text = "、".join(
                f"{p.get('title', p['product_id'])} (`{p['product_id']}`)"
                for p in products
            ) or "无"
            answer = turn["answer"].strip() or "(空)"
            status_tag = ""
            if not turn.get("completed_via_done", False):
                status_tag = "（⚠️ 未收到 done）"
            lines.extend(
                [
                    f"### 第 {idx} 轮 {status_tag}".rstrip(),
                    "",
                    f"- 输入：{turn['query']}",
                    f"- 耗时：`{turn['elapsed_s']}s`",
                    f"- 命中商品：{product_text}",
                    f"- 错误：{'; '.join(turn['errors']) or turn['client_error'] or '无'}",
                    "",
                    "服务回答：",
                    "",
                    "```text",
                    answer,
                    "```",
                    "",
                ]
            )
    return "\n".join(lines)


def write_outputs(
    results: list[dict[str, Any]],
    base_url: str,
    out_json: Path,
    out_md: Path,
    is_partial: bool,
) -> None:
    suffix = ".partial" if is_partial else ""
    Path(str(out_json) + suffix).write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    Path(str(out_md) + suffix).write_text(
        render_markdown(results, base_url), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--cases", default="delivery/评测集.md")
    parser.add_argument("--out-json", default="delivery/当前服务评测结果.raw.json")
    parser.add_argument("--out-md", default="delivery/当前服务评测结果.md")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    out_json = Path(args.out_json)
    out_md = Path(args.out_md)

    cases = parse_cases(Path(args.cases))
    if args.limit:
        cases = cases[: args.limit]
    total = len(cases)

    results: list[dict[str, Any]] = []
    abnormal: list[str] = []
    for index, case in enumerate(cases, 1):
        print(f"[{index}/{total}] {case.case_id}: {' / '.join(case.turns)}", flush=True)
        try:
            result = evaluate_case(case, base, args.timeout)
        except KeyboardInterrupt:
            print(f"  用户中断，已完成 {len(results)}/{total} 个 case，写入 partial 结果…", flush=True)
            write_outputs(results, base, out_json, out_md, is_partial=True)
            raise
        results.append(result)
        if result.get("has_incomplete_turn"):
            abnormal.append(result["case_id"])
            print(f"  ⚠️ {case.case_id} 存在未收到 done 的轮次", flush=True)
        # 增量落盘：每完成一个 case 就写一次 partial，防止进程被杀白跑
        write_outputs(results, base, out_json, out_md, is_partial=True)
        print(f"  ✅ 已写入 {index}/{total}", flush=True)

    # 全部跑完，写最终正式版（去掉 .partial 后缀的同名覆盖）
    out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md.write_text(render_markdown(results, base), encoding="utf-8")
    # 清理 partial
    for p in (Path(str(out_json) + ".partial"), Path(str(out_md) + ".partial")):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    print(f"Wrote {args.out_json}")
    print(f"Wrote {args.out_md}")
    if abnormal:
        print(f"⚠️ 以下 case 存在未收到 done 的轮次：{', '.join(abnormal)}")
    else:
        print("✅ 所有 case 均以 done 事件正常结束。")


if __name__ == "__main__":
    main()
