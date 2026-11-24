#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rtsp_streaming: 讀取影像來源並發布至 MediaMTX."""

# ------------------------------------------------------------------------------------ #
# Import
# ------------------------------------------------------------------------------------ #
import argparse

from vision_core_pkg.framebuffer import RTSPFrameBuffer
from vision_pkg._cli import CLIHelpFormatter
from vision_pkg.streaming._framebuffer_streaming import (
    add_output_arguments,
    add_timeout_arguments,
    validate_output_arguments,
    validate_timeout_arguments,
    run_streaming,
)


# ------------------------------------------------------------------------------------ #
# 來源預設參數
# ------------------------------------------------------------------------------------ #
SOURCE_URL = "rtsp://192.168.144.108"


# ------------------------------------------------------------------------------------ #
# 主程式
# ------------------------------------------------------------------------------------ #
def main(argv: list[str] | None = None) -> int:
    # --- 建立來源與共用參數 --- #
    parser = argparse.ArgumentParser(
        prog="main_streaming --rtsp",
        description="RTSP H.264 影像接收與 RTSP 串流發布",
        allow_abbrev=False,
        formatter_class=CLIHelpFormatter,
        epilog=(
            "使用範例:\n"
            "  ros2 run vision_pkg main_streaming --rtsp\n"
            "  ros2 run vision_pkg main_streaming --rtsp "
            "--source-url rtsp://192.168.144.108\n"
            "  ros2 run vision_pkg main_streaming --rtsp "
            "--output-url rtsp://127.0.0.1:8554/live/camera\n"
            "  ros2 run vision_pkg main_streaming --rtsp "
            "--output-fps 30 --output-bitrate 4M\n"
            "  ros2 run vision_pkg main_streaming --rtsp "
            "--open-timeout 10.0 --read-timeout 1.0\n"
        ),
    )

    source_group = parser.add_argument_group("RTSP 影像來源參數")
    source_group.add_argument(
        "--source-url",
        type=str,
        default=SOURCE_URL,
        metavar="URL",
        help="RTSP 影像來源位址 (rtsp:// 或 rtsps://)",
    )
    add_output_arguments(parser)
    add_timeout_arguments(parser)
    args = parser.parse_args(argv)

    # --- 驗證來源與共用參數 --- #
    validate_output_arguments(parser, args)
    validate_timeout_arguments(parser, args)
    args.source_url = args.source_url.strip()
    if not args.source_url.startswith(("rtsp://", "rtsps://")):
        parser.error("source-url 必須為 RTSP 或 RTSPS 位址")
    if args.source_url == args.output_url:
        parser.error("RTSP 輸入與輸出網址不可相同")

    # --- 共用流程負責推流與資源釋放 --- #
    return run_streaming(
        lambda: RTSPFrameBuffer(
            src=args.source_url,
            timeout=args.open_timeout,
        ),
        output_url=args.output_url,
        output_fps=args.output_fps,
        output_bitrate=args.output_bitrate,
        read_timeout=args.read_timeout,
    )


# ------------------------------------------------------------------------------------ #
# 程式進入點
# ------------------------------------------------------------------------------------ #
if __name__ == "__main__":
    raise SystemExit(main())
