#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v4l2_streaming: 讀取影像來源並發布至 MediaMTX."""

# ------------------------------------------------------------------------------------ #
# Import
# ------------------------------------------------------------------------------------ #
import argparse

from vision_core_pkg.framebuffer import V4L2FrameBuffer
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
DEVICE = "/dev/video0"
WIDTH = 1280
HEIGHT = 720
CAMERA_FPS = 30
FOURCC = "MJPG"


# ------------------------------------------------------------------------------------ #
# 主程式
# ------------------------------------------------------------------------------------ #
def main(argv: list[str] | None = None) -> int:
    # --- 建立來源與共用參數 --- #
    parser = argparse.ArgumentParser(
        prog="main_streaming --v4l2",
        description="V4L2 USB Webcam / HDMI 影像擷取與 RTSP 串流發布",
        allow_abbrev=False,
        formatter_class=CLIHelpFormatter,
        epilog=(
            "使用範例:\n"
            "  ros2 run vision_pkg main_streaming --v4l2\n"
            "  ros2 run vision_pkg main_streaming --v4l2 "
            "--device /dev/video2\n"
            "  ros2 run vision_pkg main_streaming --v4l2 "
            "--width 1920 --height 1080\n"
            "  ros2 run vision_pkg main_streaming --v4l2 "
            "--camera-fps 60 --output-fps 30\n"
            "  ros2 run vision_pkg main_streaming --v4l2 --fourcc MJPG\n"
            "  ros2 run vision_pkg main_streaming --v4l2 "
            "--output-bitrate 4M\n"
            "  ros2 run vision_pkg main_streaming --v4l2 "
            "--output-url rtsp://127.0.0.1:8554/live/camera\n"
        ),
    )

    source_group = parser.add_argument_group("V4L2 影像來源參數")
    source_group.add_argument(
        "--device",
        type=str,
        default=DEVICE,
        metavar="DEVICE",
        help="V4L2 相機裝置路徑",
    )
    source_group.add_argument(
        "--width",
        type=int,
        default=WIDTH,
        metavar="WIDTH",
        help="影像寬度 (Pixels)",
    )
    source_group.add_argument(
        "--height",
        type=int,
        default=HEIGHT,
        metavar="HEIGHT",
        help="影像高度 (Pixels)",
    )
    source_group.add_argument(
        "--camera-fps",
        type=int,
        default=CAMERA_FPS,
        metavar="FPS",
        help="相機擷取影格率 (Frames per Second)",
    )
    source_group.add_argument(
        "--fourcc",
        type=str.upper,
        default=FOURCC,
        choices=("MJPG", "YUYV", "YUY2", "UYVY", "NV12"),
        help="相機影像格式, 解析度,FPS 與格式必須為裝置支援的組合",
    )
    add_output_arguments(parser)
    add_timeout_arguments(parser)
    args = parser.parse_args(argv)

    # --- 驗證來源與共用參數 --- #
    validate_output_arguments(parser, args)
    validate_timeout_arguments(parser, args)
    args.device = args.device.strip()
    if not args.device:
        parser.error("device 不可為空字串")
    if args.width <= 0:
        parser.error("width 必須大於 0")
    if args.height <= 0:
        parser.error("height 必須大於 0")
    if args.camera_fps <= 0:
        parser.error("camera-fps 必須大於 0")

    # --- 共用流程負責推流與資源釋放 --- #
    return run_streaming(
        lambda: V4L2FrameBuffer(
            device=args.device,
            width=args.width,
            height=args.height,
            fps=args.camera_fps,
            fourcc=args.fourcc,
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
