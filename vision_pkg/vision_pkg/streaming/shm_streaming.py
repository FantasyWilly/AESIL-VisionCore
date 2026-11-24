#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shm_streaming: 讀取影像來源並發布至 MediaMTX."""

# ------------------------------------------------------------------------------------ #
# Import
# ------------------------------------------------------------------------------------ #
import argparse

from vision_core_pkg.framebuffer import SHMFrameBuffer
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
SOCKET_PATH = "/tmp/streaming.sock"
WIDTH = 1280
HEIGHT = 720


# ------------------------------------------------------------------------------------ #
# 主程式
# ------------------------------------------------------------------------------------ #
def main(argv: list[str] | None = None) -> int:
    # --- 建立來源與共用參數 --- #
    parser = argparse.ArgumentParser(
        prog="main_streaming --shm",
        description="SHM BGR 影像接收與 RTSP 串流發布",
        allow_abbrev=False,
        formatter_class=CLIHelpFormatter,
        epilog=(
            "使用範例:\n"
            "  ros2 run vision_pkg main_streaming --shm\n"
            "  ros2 run vision_pkg main_streaming --shm "
            "--socket-path /tmp/video_streaming.sock\n"
            "  ros2 run vision_pkg main_streaming --shm "
            "--width 1920 --height 1080\n"
            "  ros2 run vision_pkg main_streaming --shm "
            "--output-fps 30 --output-bitrate 4M\n"
            "  ros2 run vision_pkg main_streaming --shm "
            "--output-url rtsp://127.0.0.1:8554/live/camera\n"
            "  ros2 run vision_pkg main_streaming --shm "
            "--open-timeout 10.0 --read-timeout 1.0\n"
        ),
    )

    source_group = parser.add_argument_group("SHM 影像來源參數")
    source_group.add_argument(
        "--socket-path",
        type=str,
        default=SOCKET_PATH,
        metavar="PATH",
        help="SHM Socket 來源路徑",
    )
    source_group.add_argument(
        "--width",
        type=int,
        default=WIDTH,
        metavar="WIDTH",
        help="影像寬度 (Pixels), 必須與 SHM 發送端一致",
    )
    source_group.add_argument(
        "--height",
        type=int,
        default=HEIGHT,
        metavar="HEIGHT",
        help="影像高度 (Pixels), 必須與 SHM 發送端一致",
    )
    add_output_arguments(parser)
    add_timeout_arguments(parser)
    args = parser.parse_args(argv)

    # --- 驗證來源與共用參數 --- #
    validate_output_arguments(parser, args)
    validate_timeout_arguments(parser, args)
    args.socket_path = args.socket_path.strip()
    if not args.socket_path:
        parser.error("socket-path 不可為空字串")
    if args.width <= 0:
        parser.error("width 必須大於 0")
    if args.height <= 0:
        parser.error("height 必須大於 0")

    # --- 共用流程負責推流與資源釋放 --- #
    return run_streaming(
        lambda: SHMFrameBuffer(
            src=args.socket_path,
            width=args.width,
            height=args.height,
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
