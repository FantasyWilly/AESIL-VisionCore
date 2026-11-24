#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
File    : main_streaming.py
Author  : FantasyWilly
SPDX-License-Identifier: Apache-2.0

功能總覽:
    • 統一影像串流發布啟動入口
    • 選擇影像來源並發布至 MediaMTX
    • 預設使用 V4L2 影像來源
    • 支援動態載入對應的影像串流模組
    • 將剩餘命令列參數傳遞至指定來源模組

遵循:
    • Google Python Style Guide (含區段標題)
    • PEP 8 (行寬 ≤ 88, snake_case, 2 空行區段分隔)
"""

# ------------------------------------------------------------------------------------ #
# Import
# ------------------------------------------------------------------------------------ #
# 標準庫
import argparse
from importlib import import_module


# ------------------------------------------------------------------------------------ #
# 主程式
# ------------------------------------------------------------------------------------ #
def main(argv: list[str] | None = None) -> int:
    # --- 建立命令列參數解析器 --- #
    parser = argparse.ArgumentParser(
        prog="main_streaming",
        description="影像串流發布系統 (MediaMTX Video Streaming)",
        add_help=False,
        allow_abbrev=False,
        formatter_class=argparse.RawTextHelpFormatter,
    )

    # --- 建立影像來源參數群組 --- #
    source_group = parser.add_argument_group("影像來源")
    sources = source_group.add_mutually_exclusive_group()

    sources.add_argument(
        "--v4l2",
        dest="source",
        action="store_const",
        const="v4l2",
        help="Webcam / HDMI (預設)",
    )
    sources.add_argument(
        "--rtsp",
        dest="source",
        action="store_const",
        const="rtsp",
        help="RTSP H.264",
    )
    sources.add_argument(
        "--udp",
        dest="source",
        action="store_const",
        const="udp",
        help="UDP RTP/H.264",
    )
    sources.add_argument(
        "--shm",
        dest="source",
        action="store_const",
        const="shm",
        help="SHM BGR 影像",
    )
    sources.add_argument(
        "--pi-mipi",
        "--mipi",
        dest="source",
        action="store_const",
        const="pi_mipi",
        help="Raspberry Pi MIPI 相機",
    )

    # --- 建立說明參數群組 --- #
    help_group = parser.add_argument_group("其他選項")

    help_group.add_argument(
        "-h",
        "--help",
        action="store_true",
        help="顯示系統及指定影像來源的參數說明",
    )

    # --- 設定預設影像來源並解析參數 --- #
    parser.set_defaults(source="v4l2")
    args, remaining = parser.parse_known_args(argv)

    # --- 顯示影像串流系統說明 --- #
    if args.help:
        parser.print_help()
        source_name = args.source.upper().replace("_", " ")
        print(f"\n以下為 {source_name} 影像來源的參數:\n", flush=True)
        remaining = ["--help"]

    # --- 動態載入對應影像串流模組 --- #
    module = import_module(
        f"vision_pkg.streaming.{args.source}_streaming"
    )

    # --- 啟動來源程式並傳遞剩餘參數 --- #
    return module.main(remaining)


# ------------------------------------------------------------------------------------ #
# 程式進入點
# ------------------------------------------------------------------------------------ #
if __name__ == "__main__":
    raise SystemExit(main())