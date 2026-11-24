#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""udp_streaming: 讀取影像來源並發布至 MediaMTX."""

# ------------------------------------------------------------------------------------ #
# Import
# ------------------------------------------------------------------------------------ #
import argparse

from vision_core_pkg.framebuffer import UDPFrameBuffer
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
UDP_HOST = "127.0.0.1"
UDP_PORT = 5600


# ------------------------------------------------------------------------------------ #
# 主程式
# ------------------------------------------------------------------------------------ #
def main(argv: list[str] | None = None) -> int:
    # --- 建立來源與共用參數 --- #
    parser = argparse.ArgumentParser(
        prog="main_streaming --udp",
        description="UDP RTP/H.264 影像接收與 RTSP 串流發布",
        allow_abbrev=False,
        formatter_class=CLIHelpFormatter,
        epilog=(
            "使用範例:\n"
            "  ros2 run vision_pkg main_streaming --udp\n"
            "  ros2 run vision_pkg main_streaming --udp --host 127.0.0.1\n"
            "  ros2 run vision_pkg main_streaming --udp --port 5600\n"
            "  ros2 run vision_pkg main_streaming --udp "
            "--output-fps 30 --output-bitrate 4M\n"
            "  ros2 run vision_pkg main_streaming --udp "
            "--output-url rtsp://127.0.0.1:8554/live/camera\n"
            "  ros2 run vision_pkg main_streaming --udp "
            "--open-timeout 10.0 --read-timeout 1.0\n"
        ),
    )

    source_group = parser.add_argument_group("UDP 影像來源參數")
    source_group.add_argument(
        "--host",
        type=str,
        default=UDP_HOST,
        metavar="HOST",
        help="UDP 接收端綁定位址",
    )
    source_group.add_argument(
        "--port",
        type=int,
        default=UDP_PORT,
        metavar="PORT",
        help="UDP 接收連接埠 (1-65535)",
    )
    add_output_arguments(parser)
    add_timeout_arguments(parser)
    args = parser.parse_args(argv)

    # --- 驗證來源與共用參數 --- #
    validate_output_arguments(parser, args)
    validate_timeout_arguments(parser, args)
    args.host = args.host.strip()
    if not args.host:
        parser.error("host 不可為空字串")
    if not 1 <= args.port <= 65535:
        parser.error("port 必須介於 1 到 65535")

    # --- 共用流程負責推流與資源釋放 --- #
    return run_streaming(
        lambda: UDPFrameBuffer(
            udp_host=args.host,
            udp_port=args.port,
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
