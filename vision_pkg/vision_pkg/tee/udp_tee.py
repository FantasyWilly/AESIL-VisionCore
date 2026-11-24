
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
File    : udp_tee.py
Author  : FantasyWilly
SPDX-License-Identifier: Apache-2.0

功能總覽:
    • 使用 UDPFrameBuffer 接收 UDP RTP/H.264 影像串流
    • 自動取得來源影像解析度並轉換為 BGR 格式
    • 使用 GStreamer tee 將影像分流至多個 SHM Socket
    • 支援設定 UDP 接收位址, 連接埠與 SHM 容量
    • SHM 僅傳送影像資料, 不包含來源時間戳記

遵循:
    • Google Python Style Guide
    • PEP 8
"""

# ------------------------------------------------------------------------------------ #
# Import
# ------------------------------------------------------------------------------------ #
# 標準庫
import argparse

# 專案模組
from vision_core_pkg.framebuffer import UDPFrameBuffer
from vision_pkg.tee._framebuffer_tee import run_tee, validate_outputs
from vision_pkg._cli import CLIHelpFormatter


# ------------------------------------------------------------------------------------ #
# UDP 與 SHM 預設參數
# ------------------------------------------------------------------------------------ #
# UDP 接收端綁定位址與連接埠
UDP_HOST = "127.0.0.1"
UDP_PORT = 5600

# SHM 輸出 Socket 路徑
OUTPUT_PATH = [
    "/tmp/streaming.sock",
    "/tmp/video_streaming.sock",
]

# SHM 緩衝區大小, 64 MiB
SHM_SIZE = 64 * 1024 * 1024


# ------------------------------------------------------------------------------------ #
# UDP SHM 分流主程式
# ------------------------------------------------------------------------------------ #
def main(argv: list[str] | None = None) -> int:
    """
    初始化 UDP 影像接收器並啟動 GStreamer SHM 分流

    args:
        argv: 命令列參數列表, None 表示使用 sys.argv

    returns:
        int: 正常結束時回傳 0
    """

    # --- 建立命令列參數解析器 --- #
    parser = argparse.ArgumentParser(
        prog="main_tee --udp",
        description="UDP RTP/H.264 影像接收與 SHM 分流",
        allow_abbrev=False,
        formatter_class=CLIHelpFormatter,
        epilog=(
            "使用範例:\n"
            "  ros2 run vision_pkg main_tee --udp\n"
            "  ros2 run vision_pkg main_tee --udp --port 5600\n"
            "  ros2 run vision_pkg main_tee --udp --host 0.0.0.0\n"
            "  ros2 run vision_pkg main_tee --udp --output_path /tmp/video.sock\n"
        ),
    )

    # --- UDP 接收參數 --- #
    udp_group = parser.add_argument_group("UDP 接收參數")

    udp_group.add_argument(
        "--host",
        type=str,
        default=UDP_HOST,
        metavar="HOST",
        help="UDP 接收端綁定位址",
    )

    udp_group.add_argument(
        "--port",
        type=int,
        default=UDP_PORT,
        metavar="PORT",
        help="UDP 接收連接埠 (1-65535)",
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
        help="SHM Socket 輸出路徑, 支援多個路徑",
    )

    # --- 解析命令列參數 --- #
    args = parser.parse_args(argv)

    # --- 驗證 UDP 接收參數 --- #
    if not args.host.strip():
        parser.error("host 不可為空字串")

    if not 1 <= args.port <= 65535:
        parser.error("port 必須介於 1 到 65535")

    # --- 預先驗證 SHM 輸出設定 --- #
    paths = validate_outputs(
        parser,
        args.output_path,
        1,
        1,
        args.shm_size,
    )

    # --- 初始化 UDP 影像來源 --- #
    receiver = UDPFrameBuffer(
        udp_host=args.host,
        udp_port=args.port,
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
