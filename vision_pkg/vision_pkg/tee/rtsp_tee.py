
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
File    : rtsp_tee.py
Author  : FantasyWilly
SPDX-License-Identifier: Apache-2.0

功能總覽:
    • 使用 RTSPFrameBuffer 接收 RTSP H.264 影像串流
    • 自動取得來源影像解析度並轉換為 BGR 格式
    • 使用 GStreamer tee 將影像分流至多個 SHM Socket
    • 支援設定 RTSP URL 與 SHM 容量
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
from vision_core_pkg.framebuffer import RTSPFrameBuffer
from vision_pkg._cli import CLIHelpFormatter
from vision_pkg.tee._framebuffer_tee import run_tee, validate_outputs


# ------------------------------------------------------------------------------------ #
# RTSP 與 SHM 預設參數
# ------------------------------------------------------------------------------------ #
# RTSP 影像來源位址
RTSP_URL = "rtsp://192.168.144.108"

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
    初始化 RTSP 影像接收器並啟動 GStreamer SHM 分流

    args:
        argv: 命令列參數列表, None 表示使用 sys.argv

    returns:
        int: 正常結束時回傳 0
    """

    # --- 建立命令列參數解析器 --- #
    parser = argparse.ArgumentParser(
        prog="main_tee --rtsp",
        description="RTSP H.264 影像接收與 SHM 分流",
        allow_abbrev=False,
        formatter_class=CLIHelpFormatter,
        epilog=(
            "使用範例:\n"
            "  ros2 run vision_pkg main_tee --rtsp\n"
            "  ros2 run vision_pkg main_tee --rtsp "
            "--url rtsp://192.168.144.108\n"
            "  ros2 run vision_pkg main_tee --rtsp "
            "--output_path /tmp/video.sock\n"
            "  ros2 run vision_pkg main_tee --rtsp "
            "--output_path /tmp/streaming.sock /tmp/video_streaming.sock\n"
        ),
    )

    # --- RTSP 影像來源參數 --- #
    rtsp_group = parser.add_argument_group("RTSP 影像來源參數")

    rtsp_group.add_argument(
        "--url",
        type=str,
        default=RTSP_URL,
        metavar="URL",
        help="RTSP 影像來源位址 (rtsp:// 或 rtsps://)",
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

    # --- 驗證 RTSP 來源位址 --- #
    if not args.url.startswith(("rtsp://", "rtsps://")):
        parser.error("URL 必須為 RTSP 或 RTSPS 位址")

    # --- 預先驗證 SHM 輸出設定 --- #
    paths = validate_outputs(
        parser,
        args.output_path,
        1,
        1,
        args.shm_size,
    )

    # --- 初始化 RTSP 影像來源 --- #
    receiver = RTSPFrameBuffer(
        src=args.url,
    )

    # --- 取得實際影像解析度並重新驗證 SHM 容量 --- #
    try:
        width, height = receiver.get_frame_size()

        paths = validate_outputs(
            parser,
            paths,
            width,
            height,
            args.shm_size,
        )

    except BaseException:
        receiver.release()
        raise

    # --- 啟動 GStreamer SHM 影像分流 --- #
    run_tee(
        receiver,
        width,
        height,
        paths,
        args.shm_size,
    )

    return 0


# ------------------------------------------------------------------------------------ #
# 程式進入點
# ------------------------------------------------------------------------------------ #
if __name__ == "__main__":
    raise SystemExit(main())
