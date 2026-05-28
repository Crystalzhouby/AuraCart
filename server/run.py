"""
AuraCart 启动脚本。

通过 ``--log`` 参数控制日志级别，覆盖 config.yaml 中的默认值。
其余参数透传给 uvicorn。

用法::

    python run.py                          # 默认 INFO
    python run.py --log DEBUG              # DEBUG 级别
    python run.py --log DEBUG --port 8080  # 指定端口
"""

import argparse
import os
import sys
from pathlib import Path

# 确保 server/ 在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn


def _parse_args():
    """解析 --log 参数，其余透传 uvicorn。"""
    parser = argparse.ArgumentParser(description="AuraCart 服务启动")
    parser.add_argument(
        "--log", dest="log_level", default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别，覆盖 config.yaml。默认 INFO。",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="绑定地址 (默认 127.0.0.1)",
    )
    parser.add_argument(
        "--port", type=int, default=8000,
        help="绑定端口 (默认 8000)",
    )
    parser.add_argument(
        "--reload", action="store_true", default=False,
        help="开启热重载 (默认关闭)",
    )
    return parser.parse_args()


def main():
    args = _parse_args()

    # 通过环境变量注入日志级别，config.py 中的 Settings.from_yaml() 会读取
    if args.log_level:
        os.environ["AURACART_LOG_LEVEL"] = args.log_level

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_excludes=["log/*", "log/", "*.log"],
        log_level="info",
    )


if __name__ == "__main__":
    main()
