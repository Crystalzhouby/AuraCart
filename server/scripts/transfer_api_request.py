"""
将 curl 命令行中的中文查询参数进行 URL 编码，生成可直接执行的命令。

用法:
    python transfer_api_request.py

    输入原始 curl 命令（交互式），输出编码后的 curl 命令。

    也可直接导入使用:
        from transfer_api_request import encode_curl_command
        result = encode_curl_command(...)

原因:
    curl 不会自动对 URL 中的中文字符进行百分号编码，导致服务端接收到乱码。
    FastAPI/Uvicorn 依赖底层 HTTP 解析器，未编码的非 ASCII 字符可能无法正确解析。
"""

import re
import sys
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse


def encode_url_query(url: str) -> str:
    """
    将 URL 查询字符串中的参数值进行 URL 编码。

    参数:
        url: 可能包含未编码中文字符的完整 URL。

    返回值:
        查询参数已百分号编码的 URL。
    """
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query, keep_blank_values=True)

    encoded_pairs = []
    for key, values in query_params.items():
        for v in values:
            encoded_pairs.append((key, v))

    encoded_query = urlencode(encoded_pairs, doseq=True, safe="/")
    return urlunparse(parsed._replace(query=encoded_query))


def encode_curl_command(cmd: str) -> str:
    """
    解析 curl 命令，对其 URL 中的中文参数编码，返回修正后的命令。

    支持格式:
        curl [选项] "URL"
        curl [选项] URL

    参数:
        cmd: 原始 curl 命令字符串。

    返回值:
        URL 查询参数已编码的 curl 命令字符串。
    """
    url_pattern = re.compile(r"""(['"])(https?://[^'"]+)\1|(\s)(https?://\S+)""")

    def replace_url(match):
        quote_char = match.group(1)
        if quote_char:
            url = match.group(2)
            encoded = encode_url_query(url)
            return f'{quote_char}{encoded}{quote_char}'
        else:
            space = match.group(3)
            url = match.group(4)
            encoded = encode_url_query(url)
            return f'{space}{encoded}'

    return url_pattern.sub(replace_url, cmd)


# ---------------------------------------------------------------------------
# 内置测试用例
# ---------------------------------------------------------------------------

_TEST_CASES = [
    (
        'curl -N "http://localhost:8000/api/search?q=推荐一款200元以下的防晒"',
        'curl -N "http://localhost:8000/api/search?q=%E6%8E%A8%E8%8D%90%E4%B8%80%E6%AC%BE200%E5%85%83%E4%BB%A5%E4%B8%8B%E7%9A%84%E9%98%B2%E6%99%92%E9%9C%9C"',
    ),
    (
        "curl http://localhost:8000/api/search?q=hello&stream=false",
        "curl http://localhost:8000/api/search?q=hello&stream=false",
    ),
]


def _run_tests() -> bool:
    """运行自测，全部通过返回 True。"""
    all_ok = True
    for raw, expected in _TEST_CASES:
        result = encode_curl_command(raw)
        ok = result == expected
        if not ok:
            print(f"  FAIL: {raw[:60]}...")
            print(f"    期望: {expected}")
            print(f"    实际: {result}")
        all_ok = all_ok and ok
    return all_ok


# ---------------------------------------------------------------------------
# 交互式入口
# ---------------------------------------------------------------------------


def main():
    # 尝试将 stdin 配置为 UTF-8（Windows 控制台下默认非 UTF-8）
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    print("请输入原始 curl 命令（输入后按回车）:")
    print('示例: curl -N "http://localhost:8000/api/search?q=推荐一款200元以下的防晒"')
    print("-" * 60)

    raw_cmd = sys.stdin.readline().strip()

    if not raw_cmd:
        print("未输入任何命令。", file=sys.stderr)
        sys.exit(1)

    result = encode_curl_command(raw_cmd)

    print()
    print("编码后的 curl 命令（可直接复制执行）:")
    print("-" * 60)
    print(result)
    print("-" * 60)

    url_match = re.search(r"""(['"]?)(https?://[^'"]+)\1""", result)
    if url_match:
        encoded_url = url_match.group(2)
        print()
        print("编码后的 URL:")
        print(encoded_url)


if __name__ == "__main__":
    # 带 --test 参数运行时执行自测
    if "--test" in sys.argv:
        ok = _run_tests()
        if ok:
            print("全部测试通过。")
        sys.exit(0 if ok else 1)

    main()
