#!/usr/bin/env python3
"""Browser_Agent CLI（只在电脑上由人运行，Agent 调不到）。

  browser-login --member <名字>   打开该成员专用的 Chrome，人工登录各网站；cookie 留在 profile 里供 browse 用
"""
import argparse
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Agent_Runtime")); import bootstrap  # noqa: E402,E702

import browser_chrome as bc  # noqa: E402
import browser_jobs  # noqa: E402
import members  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(prog="Browser_Agent", description="FAM 浏览器")
    sub = p.add_subparsers(dest="cmd", required=True)
    lg = sub.add_parser("browser-login", help="打开成员专用 Chrome 手动登录")
    lg.add_argument("--member", required=True)
    args = p.parse_args()

    names = members.member_names()
    if args.member not in names:
        print(f"[错误] 未登记的成员：{args.member}。已登记：{'、'.join(names) or '（无）'}")
        return 1
    if browser_jobs.busy():
        print("[错误] 浏览任务进行中，等它结束再登录")
        return 1
    try:
        bc.ensure(args.member, bc.load_cfg())
    except bc.ChromeError as e:
        print(f"[错误] {e}")
        return 1
    print(f"已打开 {args.member} 的浏览器。在窗口里登录各网站后直接关掉窗口即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
