#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pi_mipi_streaming: 讀取影像來源並發布至 MediaMTX."""

# ------------------------------------------------------------------------------------ #
# Import
# ------------------------------------------------------------------------------------ #
import argparse

from vision_core_pkg.framebuffer import PiMIPIFrameBuffer
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
CAMERA_NUM = 0
WIDTH = 1280
HEIGHT = 720
CAMERA_FPS = 30


# ------------------------------------------------------------------------------------ #
# 主程式
# ------------------------------------------------------------------------------------ #
def main(argv: list[str] | None = None) -> int:
    # --- 建立來源與共用參數 --- #
    parser = argparse.ArgumentParser(
        prog="main_streaming --pi-mipi",
        description="Raspberry Pi MIPI 影像擷取與 RTSP 串流發布",
        allow_abbrev=False,
        formatter_class=CLIHelpFormatter,
        epilog=(
            "使用範例:\n"
            "  ros2 run vision_pkg main_streaming --pi-mipi\n"
            "  ros2 run vision_pkg main_streaming --pi-mipi --camera-num 1\n"
            "  ros2 run vision_pkg main_streaming --pi-mipi "
            "--width 1920 --height 1080\n"
            "  ros2 run vision_pkg main_streaming --pi-mipi "
            "--camera-fps 60 --output-fps 30\n"
            "  ros2 run vision_pkg main_streaming --pi-mipi "
            "--output-bitrate 4M\n"
            "  ros2 run vision_pkg main_streaming --pi-mipi "
            "--output-url rtsp://127.0.0.1:8554/live/camera\n"
        ),
    )

    mipi_group = parser.add_argument_group("MIPI 相機參數")
    mipi_group.add_argument(
        "--camera-num",
        type=int,
        default=CAMERA_NUM,
        metavar="NUM",
        help="MIPI 相機編號, 從 0 開始",
    )
    mipi_group.add_argument(
        "--width",
        type=int,
        default=WIDTH,
        metavar="WIDTH",
        help="影像寬度 (Pixels)",
    )
    mipi_group.add_argument(
        "--height",
        type=int,
        default=HEIGHT,
        metavar="HEIGHT",
        help="影像高度 (Pixels)",
    )
    mipi_group.add_argument(
        "--camera-fps",
        type=int,
        default=CAMERA_FPS,
        metavar="FPS",
        help="相機擷取影格率 (Frames per Second)",
    )
    add_output_arguments(parser)
    add_timeout_arguments(parser)
    args = parser.parse_args(argv)

    # --- 驗證來源與共用參數 --- #
    validate_output_arguments(parser, args)
    validate_timeout_arguments(parser, args)
    if args.camera_num < 0:
        parser.error("camera-num 不可小於 0")
    if args.width <= 0:
        parser.error("width 必須大於 0")
    if args.height <= 0:
        parser.error("height 必須大於 0")
    if args.camera_fps <= 0:
        parser.error("camera-fps 必須大於 0")

    # --- 共用流程負責推流與資源釋放 --- #
    return run_streaming(
        lambda: PiMIPIFrameBuffer(
            out_w=args.width,
            out_h=args.height,
            camera_num=args.camera_num,
            fps=args.camera_fps,
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
