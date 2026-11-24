#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""共用串流參數, 驗證與 FrameBuffer 到 MediaMTX 的推流流程."""

# ------------------------------------------------------------------------------------ #
# Import
# ------------------------------------------------------------------------------------ #
import argparse
from collections.abc import Callable
from contextlib import ExitStack
import logging
import math
import time
from typing import Protocol

import numpy as np

from vision_core_pkg.streaming import GStreamerVideoOutput

# ------------------------------------------------------------------------------------ #
# RTSP 串流預設參數
# ------------------------------------------------------------------------------------ #
OUTPUT_URL = "rtsp://127.0.0.1:8554/live/stream"

OUTPUT_FPS = 30

OUTPUT_BITRATE = "2M"

# ------------------------------------------------------------------------------------ #
# Timeout 與警告預設參數
# ------------------------------------------------------------------------------------ #
OPEN_TIMEOUT = 5.0

READ_TIMEOUT = 0.5

WARNING_INTERVAL = 5.0

# ------------------------------------------------------------------------------------ #
# FrameBuffer 介面定義
# ------------------------------------------------------------------------------------ #
class FrameBufferProtocol(Protocol):
    """定義影像串流模組所需的 FrameBuffer 共用介面"""

    def get_frame_size(self) -> tuple[int, int]:
        """取得影像解析度."""
        ...

    def read_with_timestamp(
        self,
        timeout: float,
    ) -> tuple[np.ndarray, int] | None:
        """讀取最新影格與影像接收時間戳記."""
        ...

    def release(self) -> None:
        """釋放影像接收器資源."""
        ...

# ------------------------------------------------------------------------------------ #
# 建立 RTSP 串流發布參數
# ------------------------------------------------------------------------------------ #
def add_output_arguments(
    parser: argparse.ArgumentParser,
    *,
    output_url: str = OUTPUT_URL,
    output_fps: int = OUTPUT_FPS,
    output_bitrate: str = OUTPUT_BITRATE,
) -> None:
    """建立共用的 RTSP 串流發布參數"""

    output_group = parser.add_argument_group("RTSP 串流發布參數")

    output_group.add_argument(
        "--output-url",
        type=str,
        default=output_url,
        metavar="URL",
        help="MediaMTX RTSP 串流發布位址",
    )

    output_group.add_argument(
        "--output-fps",
        type=int,
        default=output_fps,
        metavar="FPS",
        help="RTSP 串流輸出影格率 (Frames per Second)",
    )

    output_group.add_argument(
        "--output-bitrate",
        type=str,
        default=output_bitrate,
        metavar="BITRATE",
        help="串流編碼位元率, 例如 500K, 2M, 4M",
    )

# ------------------------------------------------------------------------------------ #
# 建立 Timeout 參數
# ------------------------------------------------------------------------------------ #
def add_timeout_arguments(
    parser: argparse.ArgumentParser,
    *,
    open_timeout: float = OPEN_TIMEOUT,
    read_timeout: float = READ_TIMEOUT,
) -> None:
    """建立共用的影像來源逾時參數"""

    timeout_group = parser.add_argument_group("Timeout 逾時參數")

    timeout_group.add_argument(
        "--open-timeout",
        type=float,
        default=open_timeout,
        metavar="SEC",
        help="影像來源開啟逾時時間 (Seconds)",
    )

    timeout_group.add_argument(
        "--read-timeout",
        type=float,
        default=read_timeout,
        metavar="SEC",
        help="影像讀取逾時時間 (Seconds)",
    )

# ------------------------------------------------------------------------------------ #
# 驗證 RTSP 串流發布參數
# ------------------------------------------------------------------------------------ #
def validate_output_arguments(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
    """驗證 RTSP 串流發布參數"""

    args.output_url = args.output_url.strip()

    if not args.output_url.startswith(("rtsp://", "rtsps://")):
        parser.error("output-url 必須為 RTSP 或 RTSPS 位址")

    if args.output_fps <= 0:
        parser.error("output-fps 必須大於 0")

    args.output_bitrate = args.output_bitrate.strip()

    if not args.output_bitrate:
        parser.error("output-bitrate 不可為空字串")

# ------------------------------------------------------------------------------------ #
# 驗證 Timeout 參數
# ------------------------------------------------------------------------------------ #
def validate_timeout_arguments(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
    """驗證影像來源開啟與讀取逾時參數"""

    if not math.isfinite(args.open_timeout) or args.open_timeout <= 0:
        parser.error("open-timeout 必須為大於 0 的有限數值")

    if not math.isfinite(args.read_timeout) or args.read_timeout <= 0:
        parser.error("read-timeout 必須為大於 0 的有限數值")

# ------------------------------------------------------------------------------------ #
# 執行 GStreamer RTSP 影像串流
# ------------------------------------------------------------------------------------ #
def run_streaming(
    source_factory: Callable[[], FrameBufferProtocol],
    *,
    output_url: str = OUTPUT_URL,
    output_fps: int = OUTPUT_FPS,
    output_bitrate: str = OUTPUT_BITRATE,
    read_timeout: float = READ_TIMEOUT,
    warning_interval: float = WARNING_INTERVAL,
) -> int:
    """初始化影像來源並持續將影像串流發布至 MediaMTX"""

    # -------------------------------------------------------------------------------- #
    # 驗證內部執行參數
    # -------------------------------------------------------------------------------- #

    if not math.isfinite(read_timeout) or read_timeout <= 0:
        raise ValueError("read_timeout 必須為大於 0 的有限數值")

    if not math.isfinite(warning_interval) or warning_interval <= 0:
        raise ValueError("warning_interval 必須為大於 0 的有限數值")

    # -------------------------------------------------------------------------------- #
    # 初始化日誌
    # -------------------------------------------------------------------------------- #

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    # -------------------------------------------------------------------------------- #
    # 初始化影像來源與 RTSP 串流輸出
    # -------------------------------------------------------------------------------- #

    try:
        with ExitStack() as resources:

            # --- 初始化影像來源 --- #
            source = source_factory()

            resources.callback(source.release)

            # --- 初始化 GStreamer RTSP 串流輸出 --- #
            output = GStreamerVideoOutput(
                url=output_url,
                fps=output_fps,
                bitrate=output_bitrate,
            )

            resources.callback(output.close)

            logging.info(
                "來源已開啟, 尺寸: %s, 輸出: %s",
                source.get_frame_size(),
                output_url,
            )

            # ------------------------------------------------------------------------ #
            # 持續讀取影像並發布 RTSP 串流
            # ------------------------------------------------------------------------ #

            last_warning = time.monotonic() - warning_interval

            while True:

                sample = source.read_with_timestamp(
                    timeout=read_timeout,
                )

                # --- 影像逾時或未收到新影格 --- #
                if sample is None:
                    now = time.monotonic()

                    if now - last_warning >= warning_interval:
                        logging.warning(
                            "尚未收到新影格, 請檢查影像來源"
                        )
                        last_warning = now

                    continue

                # --- 取得影像與時間戳記 --- #
                frame, received_ns = sample

                output.submit(
                    frame,
                    received_ns=received_ns,
                )

    except KeyboardInterrupt:
        logging.info("已停止串流")

    return 0
