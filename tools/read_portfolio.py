#!/usr/bin/env python3
"""Print a read-only JSON portfolio view, even when the desktop app is closed."""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai_portfolio  # noqa: E402


def default_database():
    configured = os.getenv("SHIGUANG_DATA_DIR")
    if configured:
        return Path(configured) / "portfolio.db"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Shiguang" / "portfolio.db"
    if os.name == "nt":
        return Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "Shiguang" / "portfolio.db"
    return Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "shiguang" / "portfolio.db"


def main():
    parser = argparse.ArgumentParser(description="只读输出拾光投资持仓 JSON")
    parser.add_argument("--db", type=Path, default=default_database(), help="数据库路径")
    parser.add_argument("--day", help="查询某日基金/ETF 快照，格式 YYYY-MM-DD；不含历史现金")
    args = parser.parse_args()
    try:
        result = (ai_portfolio.dated_holdings(args.db, args.day) if args.day
                  else ai_portfolio.current_portfolio(args.db))
    except (FileNotFoundError, ValueError) as exc:
        parser.exit(1, f"读取失败：{exc}\n")
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
