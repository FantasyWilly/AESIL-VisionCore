#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
File    : pi_mipi_tee.py
Author  : FantasyWilly
SPDX-License-Identifier: Apache-2.0

功能總覽:
    • 使用 PiMIPIFrameBuffer 讀取 Raspberry Pi MIPI 相機
    • 支援設定相機編號, FPS, 解析度與相機控制參數
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
from vision_core_pkg.framebuffer import PiMIPIFrameBuffer
from vision_pkg._cli import CLIHelpFormatter
from vision_pkg.tee._framebuffer_tee import run_tee, validate_outputs


# ------------------------------------------------------------------------------------ #
# Pi MIPI 與 SHM 預設參數
# ------------------------------------------------------------------------------------ #
# 相機編號
CAMERA_NUM = 0

# 影像解析度
OUTPUT_WIDTH = 1280
OUTPUT_HEIGHT = 720

# 影像影格率
OUTPUT_FPS = 30

# SHM 輸出 Socket 路徑
OUTPUT_PATH = [
    "/tmp/streaming.sock",
    "/tmp/video_streaming.sock",
]

# SHM 緩衝區大小, 64 MiB
SHM_SIZE = 64 * 1024 * 1024


# ------------------------------------------------------------------------------------ #
# MIPI 相機控制參數
# ------------------------------------------------------------------------------------ #
# 自動對焦由 PiMIPIFrameBuffer 處理, 其他控制項依相機支援情況套用
CAMERA_CONTROLS = {
    "AeEnable": True,    # 自動曝光
    "AwbEnable": True,   # 自動白平衡
    "Brightness": 0.0,   # 亮度
    "Contrast": 1.0,     # 對比度
    "Saturation": 1.0,   # 飽和度
    "Sharpness": 1.0,    # 銳利度
}


# ------------------------------------------------------------------------------------ #
# 主程式
# ------------------------------------------------------------------------------------ #
def main(argv: list[str] | None = None) -> int:
    """
    初始化 Pi MIPI 相機並啟動 GStreamer SHM 分流

    args:
        argv: 命令列參數列表, None 表示使用 sys.argv

    returns:
        int: 正常結束時回傳 0
    """

    # --- 建立命令列參數解析器 --- #
    parser = argparse.ArgumentParser(
        prog="main_tee --pi-mipi",
        description="Raspberry Pi MIPI 影像擷取與 SHM 分流",
        allow_abbrev=False,
        formatter_class=CLIHelpFormatter,
        epilog=(
            "使用範例:\n"
            "  ros2 run vision_pkg main_tee --pi-mipi\n"
            "  ros2 run vision_pkg main_tee --pi-mipi --camera-num 0\n"
            "  ros2 run vision_pkg main_tee --pi-mipi "
            "--width 1920 --height 1080 --fps 30\n"
            "  ros2 run vision_pkg main_tee --pi-mipi --fps 30\n"
            "  ros2 run vision_pkg main_tee --pi-mipi "
            "--output_path /tmp/video.sock\n"
        ),
    )

    # --- MIPI 相機參數 --- #
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
        default=OUTPUT_WIDTH,
        metavar="WIDTH",
        help="影像寬度 (Pixels)",
    )

    mipi_group.add_argument(
        "--height",
        type=int,
        default=OUTPUT_HEIGHT,
        metavar="HEIGHT",
        help="影像高度 (Pixels)",
    )

    mipi_group.add_argument(
        "--fps",
        type=int,
        default=OUTPUT_FPS,
        metavar="FPS",
        help="影像影格率 (Frames per Second)",
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

    # --- 驗證相機參數 --- #
    if args.camera_num < 0:
        parser.error("camera-num 不可小於 0")

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

    # --- 初始化 Pi MIPI 相機 --- #
    camera = PiMIPIFrameBuffer(
        out_w=args.width,
        out_h=args.height,
        camera_num=args.camera_num,
        fps=args.fps,
        camera_controls=CAMERA_CONTROLS,
    )

    # --- 啟動 GStreamer SHM 分流 --- #
    run_tee(
        camera,
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