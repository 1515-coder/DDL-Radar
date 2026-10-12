from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .browser import (
    COURSE_CENTER_URL,
    DEFAULT_PROFILE_DIR,
    HOME_URL,
    discover_courses,
    login,
    probe_deadlines,
    scan,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mooc-ddl", description="提取中国大学 MOOC 作业和测试截止时间"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser("login", help="手动登录并保存本机会话")
    login_parser.add_argument("--url", default=HOME_URL, help="登录后首先打开的网址")
    login_parser.add_argument(
        "--profile", type=Path, default=DEFAULT_PROFILE_DIR, help="浏览器配置保存目录"
    )

    scan_parser = subparsers.add_parser("scan", help="扫描页面并保存候选接口响应")
    scan_parser.add_argument("--url", default=HOME_URL, help="首先打开的网址")
    scan_parser.add_argument(
        "--profile", type=Path, default=DEFAULT_PROFILE_DIR, help="浏览器配置读取目录"
    )
    scan_parser.add_argument(
        "--output", type=Path, default=Path("artifacts"), help="扫描结果根目录"
    )

    discover_parser = subparsers.add_parser("discover", help="从个人中心发现课程号和跳转信息")
    discover_parser.add_argument("--url", default=COURSE_CENTER_URL, help="课程中心网址")
    discover_parser.add_argument(
        "--profile", type=Path, default=DEFAULT_PROFILE_DIR, help="浏览器配置读取目录"
    )
    discover_parser.add_argument(
        "--output", type=Path, default=Path("artifacts"), help="发现结果根目录"
    )

    probe_parser = subparsers.add_parser("probe", help="探测在学课程的作业和测试接口")
    probe_parser.add_argument("courses", type=Path, help="discover 生成的 courses.json")
    probe_parser.add_argument(
        "--profile", type=Path, default=DEFAULT_PROFILE_DIR, help="浏览器配置读取目录"
    )
    probe_parser.add_argument(
        "--output", type=Path, default=Path("artifacts"), help="探测结果根目录"
    )

    serve_parser = subparsers.add_parser("serve", help="启动本地 DDL 仪表盘")
    serve_parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    serve_parser.add_argument("--port", type=int, default=8765, help="监听端口")
    serve_parser.add_argument("--open", action="store_true", help="自动打开浏览器")

    subparsers.add_parser("desktop", help="启动无端口的桌面界面")

    worker_parser = subparsers.add_parser("_worker", help=argparse.SUPPRESS)
    worker_parser.add_argument("--account", required=True)
    worker_parser.add_argument("--force-login", action="store_true")
    worker_parser.add_argument("--extra", action="append", default=[])

    materials_parser = subparsers.add_parser("_materials", help=argparse.SUPPRESS)
    materials_parser.add_argument("--account", required=True)
    materials_parser.add_argument("--scan-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    if argv is None and getattr(sys, "frozen", False) and len(sys.argv) == 1:
        argv = ["desktop"]
    args = build_parser().parse_args(argv)
    try:
        if args.command == "login":
            login(url=args.url, profile_dir=args.profile)
        elif args.command == "scan":
            scan(url=args.url, profile_dir=args.profile, output_root=args.output)
        elif args.command == "discover":
            discover_courses(url=args.url, profile_dir=args.profile, output_root=args.output)
        elif args.command == "probe":
            probe_deadlines(
                courses_file=args.courses,
                profile_dir=args.profile,
                output_root=args.output,
            )
        elif args.command == "serve":
            from .server import serve

            serve(host=args.host, port=args.port, open_browser=args.open)
        elif args.command == "_worker":
            from .worker import run

            run(args.account, args.force_login, set(args.extra))
        elif args.command == "_materials":
            from .materials import run

            run(args.account, args.scan_only)
        elif args.command == "desktop":
            from .desktop import run

            run()
    except (FileNotFoundError, RuntimeError) as exc:
        raise SystemExit(f"错误：{exc}") from exc


if __name__ == "__main__":
    main()
