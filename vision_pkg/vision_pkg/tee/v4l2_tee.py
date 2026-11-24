
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
File    : v4l2_tee.py
Author  : FantasyWilly
SPDX-License-Identifier: Apache-2.0

功能總覽:
    • 使用 V4L2FrameBuffer 讀取 USB Webcam / HDMI 擷取卡
    • 支援設定影像解析度, FPS 與 FOURCC 格式
    • 使用 GStreamer tee 將 BGR 影像分流至多個 SHM Socket
    • SHM 僅傳送影像像素資料, 不包含來源時間戳記

遵循:
    • Google Python Style Guide (含區段標題)
    • PEP 8 (行寬 ≤ 88, snake_case, 2 空行區段分隔)
"""

# ------------------------------------------------------------------------------------ #
# Import
# ------------------------------------------------------------------------------------ #
# 標準庫
import argparse

# 專案模組
from vision_core_pkg.framebuffer import V4L2FrameBuffer
from vision_pkg._cli import CLIHelpFormatter
from vision_pkg.tee._framebuffer_tee import run_tee, validate_outputs


# ------------------------------------------------------------------------------------ #
# USB Webcam / HDMI 與 SHM 預設參數
# ------------------------------------------------------------------------------------ #
# 相機裝置路徑
DEVICE = "/dev/video0"

# 影像解析度
OUTPUT_WIDTH = 1280
OUTPUT_HEIGHT = 720

# 影像影格率
OUTPUT_FPS = 30

# 相機影像格式
FOURCC = "MJPG"

# SHM 輸出 Socket 路徑
OUTPUT_PATH = [
    "/tmp/streaming.sock",
    "/tmp/video_streaming.sock",
]

# SHM 緩衝區大小, 64 MiB
SHM_SIZE = 64 * 1024 * 1024


# ------------------------------------------------------------------------------------ #
# 主程式
# ------------------------------------------------------------------------------------ #
def main(argv: list[str] | None = None) -> int:
    """
    初始化 V4L2 影像接收器並啟動 GStreamer SHM 分流

    args:
        argv: 命令列參數列表, None 表示使用 sys.argv

    returns:
        int: 正常結束時回傳 0
    """

    # --- 建立命令列參數解析器 --- #
    parser = argparse.ArgumentParser(
        prog="main_tee --v4l2",
        description="V4L2 USB Webcam / HDMI 影像擷取與 SHM 分流",
        allow_abbrev=False,
        formatter_class=CLIHelpFormatter,
        epilog=(
            "使用範例:\n"
            "  ros2 run vision_pkg main_tee --v4l2\n"
            "  ros2 run vision_pkg main_tee --v4l2 --device /dev/video2\n"
            "  ros2 run vision_pkg main_tee --v4l2 "
            "--width 1920 --height 1080 --fps 30\n"
            "  ros2 run vision_pkg main_tee --v4l2 --fourcc MJPG\n"
            "  ros2 run vision_pkg main_tee --v4l2 "
            "--output_path /tmp/video.sock\n"
        ),
    )

    # --- V4L2 影像來源參數 --- #
    v4l2_group = parser.add_argument_group("V4L2 影像來源參數")

    v4l2_group.add_argument(
        "--device",
        type=str,
        default=DEVICE,
        metavar="DEVICE",
        help="V4L2 相機裝置路徑",
    )

    v4l2_group.add_argument(
        "--width",
        type=int,
        default=OUTPUT_WIDTH,
        metavar="WIDTH",
        help="影像寬度 (Pixels)",
    )

    v4l2_group.add_argument(
        "--height",
        type=int,
        default=OUTPUT_HEIGHT,
        metavar="HEIGHT",
        help="影像高度 (Pixels)",
    )

    v4l2_group.add_argument(
        "--fps",
        type=int,
        default=OUTPUT_FPS,
        metavar="FPS",
        help="影像影格率 (Frames per Second)",
    )

    v4l2_group.add_argument(
        "--fourcc",
        type=str.upper,
        default=FOURCC,
        choices=("MJPG", "YUYV", "YUY2", "UYVY", "NV12"),
        help="相機影像格式, 解析度、FPS 與格式須為裝置支援的組合",
    )

    # --- SHM 輸出參數 --- #
    shm_group = parser.add_argument_group("SHM 輸出參數")

    shm_group.add_argument(
        "--shm_size",
        type=int,
        default=SHM_SIZE,
        metavar="SIZE",
        help="SHM 緩衝區容量 (Bytes)",
    )

    shm_group.add_argument(
        "--output_path",
        type=str,
        nargs="+",
        default=OUTPUT_PATH,
        metavar="PATH",
        help="SHM Socket 輸出路徑, 支援指定多個路徑",
    )

    # --- 解析命令列參數 --- #
    args = parser.parse_args(argv)

    # --- 驗證 V4L2 影像來源參數 --- #
    if not args.device.strip():
        parser.error("device 不可為空字串")

    if args.fps <= 0:
        parser.error("fps 必須大於 0")

    # --- 驗證 SHM 輸出設定 --- #
    paths = validate_outputs(
        parser,
        args.output_path,
        args.width,
        args.height,
        args.shm_size,
    )

    # --- 初始化 V4L2 影像來源 --- #
    receiver = V4L2FrameBuffer(
        device=args.device,
        width=args.width,
        height=args.height,
        fps=args.fps,
        fourcc=args.fourcc,
    )

    # --- 啟動 GStreamer SHM 影像分流 --- #
    run_tee(
        receiver,
        args.width,
        args.height,
        paths,
        args.shm_size,
        args.fps,
    )

    return 0


# ------------------------------------------------------------------------------------ #
# 程式進入點
# ------------------------------------------------------------------------------------ #
if __name__ == "__main__":
    raise SystemExit(main())
