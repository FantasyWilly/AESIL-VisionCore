#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
File    : _framebuffer.py
Author  : FantasyWilly
Email   : bc697522h04@gmail.com
SPDX-License-Identifier: Apache-2.0 

功能總覽:
    • 從 FrameBuffer 讀取最新 BGR 影像
    • 使用 GStreamer appsrc 將影像送入 Pipeline
    • 透過 tee 將影像分流至多個 SHM 輸出端
    • 使用 queue 避免不同接收端互相阻塞
    • 檢查輸出路徑與共享記憶體配置
    • 處理 GStreamer 錯誤與資源釋放

遵循:
    • Google Python Style Guide (含區段標題)
    • PEP 8 (行寬 ≤ 88, snake_case, 2 空行區段分隔)
"""

# ------------------------------------------------------------------------------------ #
# Import
# ------------------------------------------------------------------------------------ #
# 標準庫
import os

import gi
import numpy as np

gi.require_version("Gst", "1.0")
from gi.repository import Gst

# ------------------------------ 驗證接收影像 ------------------------------ #
def validate_outputs(parser, paths, width, height, shm_size):
    if not (1 <= width <= 8192 and 1 <= height <= 8192):
        parser.error("width / height 必須介於 1 到 8192")
    if shm_size <= 0:
        parser.error("shm_size 必須大於 0")
    paths = [os.path.abspath(path) for path in paths]
    if not paths or len(set(paths)) != len(paths):
        parser.error("output_path 不可為空或重複")
    for path in paths:
        if os.path.lexists(path):
            parser.error(f"輸出路徑已存在: {path}，請先確認舊發送端已停止")
        if not os.path.isdir(os.path.dirname(path)):
            parser.error(f"輸出目錄不存在: {os.path.dirname(path)}")
    return paths

# -------------------------- 建立 Pipeline 管線 -------------------------- #
def build_pipeline(width, height, output_path, shm_size, fps=0):
    stride = (width * 3 + 3) // 4 * 4
    capacity = max(shm_size, stride * height * 8)
    parts = [
        "appsrc name=source is-live=true format=time do-timestamp=true "
        "block=false max-buffers=1 max-bytes=0 max-time=0 leaky-type=downstream ! "
        f"video/x-raw,format=BGR,width={width},height={height},framerate={fps}/1 ! "
        "tee name=t"
    ]
    for index, path in enumerate(output_path):
        escaped = path.replace("\\", "\\\\").replace('"', '\\"')
        parts.append(
            f"t. ! queue name=branch_{index}_queue max-size-buffers=1 "
            "max-size-bytes=0 max-size-time=0 leaky=downstream ! "
            f'shmsink name=branch_{index}_sink socket-path="{escaped}" '
            f"shm-size={capacity} wait-for-connection=false sync=false async=false"
        )
    return " ".join(parts)

# ---------------------------- 讀取最新幀 & 分流 ---------------------------- #
def run_tee(framebuffer, width, height, paths, shm_size, fps=0):
    pipeline = None
    try:
        Gst.init(None)
        pipeline = Gst.parse_launch(build_pipeline(width, height, paths, shm_size, fps))
        source = pipeline.get_by_name("source")
        bus = pipeline.get_bus()
        stride = (width * 3 + 3) // 4 * 4
        packed = np.zeros((height, stride), dtype=np.uint8)
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("GStreamer 無法啟動 SHM 管線")
        print(f"FrameBuffer → BGR {width}x{height} → appsrc → tee → SHM", flush=True)
        print(f"輸出: {paths}, Ctrl+C 結束", flush=True)
        while True:
            message = bus.pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.EOS)
            if message is not None:
                if message.type == Gst.MessageType.ERROR:
                    error, debug = message.parse_error()
                    raise RuntimeError(f"GStreamer: {error}; {debug}")
                raise RuntimeError("SHM 管線提前結束")
            sample = framebuffer.read_with_timestamp(timeout=0.5)
            if sample is None:
                continue
            frame, _received_ns = sample
            if frame.dtype != np.uint8 or frame.shape != (height, width, 3):
                raise ValueError("FrameBuffer 影格必須為指定尺寸的 uint8 BGR")
            packed[:, :width * 3] = frame.reshape(height, width * 3)
            buffer = Gst.Buffer.new_wrapped(packed.tobytes())
            if fps:
                buffer.duration = Gst.SECOND // fps
            if source.emit("push-buffer", buffer) != Gst.FlowReturn.OK:
                raise RuntimeError("GStreamer 無法送入 SHM 影格")
    except KeyboardInterrupt:
        print("收到停止訊號，正在關閉來源與 SHM 管線", flush=True)
    finally:
        try:
            if pipeline is not None:
                pipeline.set_state(Gst.State.NULL)
        finally:
            framebuffer.release()
