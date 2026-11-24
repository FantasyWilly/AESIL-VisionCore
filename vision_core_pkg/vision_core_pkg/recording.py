#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
File    : recording.py
Author  : FantasyWilly
Email   : bc697522h04@gmail.com
SPDX-License-Identifier: Apache-2.0

功能總覽:
    • 錄製影像
    • 使用背景執行緒非同步寫入 MP4
    • 根據時間戳記補足缺少的影格
    • 限制最大錄影時間

遵循:
    • Google Python Style Guide (含區段標題)
    • PEP 8 (行寬 ≤ 88, snake_case, 2 空行區段分隔)
"""

# ------------------------------------------------------------------------------------ #
# Import
# ------------------------------------------------------------------------------------ #
# 標準庫
import logging
import threading
import time
from datetime import datetime
import math
from pathlib import Path
from queue import Empty, Full, Queue
from uuid import uuid4
from dataclasses import dataclass

# 第三方套件
import cv2
import numpy as np

# ROS 2 Python API
from rclpy.node import Node


# ------------------------------------------------------------------------------------ #
# RecordingConfig 讀取錄影參數設定
# ------------------------------------------------------------------------------------ #
@dataclass
class RecordingConfig:
    """
    錄影參數設定

    args:
        • recoding_enable   - 是否啟用錄影
        • directory         - 錄製影像資料夾
        • recoding_fps      - 錄製影像 FPS
        • max_minutes       - 錄製影像最多上限 (min)
    """

    recoding_enable: bool = False
    directory: str = "~/recordings"
    recoding_fps: int = 30
    max_minutes: int = 30

    # ------------------------- 讀取 ROS 2 錄影參數 ------------------------- #
    @classmethod
    def from_node(cls, node: Node) -> "RecordingConfig":

        # --- 宣告參數 --- #
        node.declare_parameter("recoding_enable", False)
        node.declare_parameter("directory", "~/recordings")
        node.declare_parameter("recoding_fps", 30)
        node.declare_parameter("max_minutes", 30)

        # --- 讀取參數 --- #
        recoding_enable = node.get_parameter("recoding_enable").value
        directory = node.get_parameter("directory").value
        recoding_fps = node.get_parameter("recoding_fps").value
        max_minutes = node.get_parameter("max_minutes").value

        cfg = cls(
            recoding_enable=recoding_enable,
            directory=directory,
            recoding_fps=recoding_fps,
            max_minutes=max_minutes,
        )

        if not recoding_enable:
            return cfg

        # --- 輸出錄影設定 --- #
        log = node.get_logger().info
        log(f"[YAML]: Recording Config")
        log(f"[Param] recoding_enable   : {cfg.recoding_enable}")
        log(f"[Param] directory         : {cfg.directory}")
        log(f"[Param] recoding_fps      : {cfg.recoding_fps}")
        log(f"[Param] max_minutes       : {cfg.max_minutes}")
        log("-------------------------------------------------------------------------")

        return cfg


# ------------------------------------------------------------------------------------ #
# 錄影程式
# ------------------------------------------------------------------------------------ #
class Recording:    
    """
    錄影參數設定

    args:
        • directory         - 錄製影像資料夾
        • recoding_fps      - 錄製影像 FPS
        • max_minutes       - 錄製影像最多上限 (min)
    """
    
    def __init__(
        self,
        directory: str = "~/recordings",
        fps: float = 30,
        max_minutes: float = 30.0,
    ):

        # --- 檢查錄影參數 --- #
        if not np.isfinite(fps) or fps <= 0:
            raise ValueError("錄影 fps 必須為有限正數")
        if not np.isfinite(max_minutes) or max_minutes <= 0:
            raise ValueError("max_minutes 必須為有限正數")

        # --- 設定錄影上限 --- #
        self.max_minutes = float(max_minutes)
        self._max_frames = math.floor(self.max_minutes * 60 * fps)

        if self._max_frames < 1:
            raise ValueError("錄影上限至少需容納一幀")

        self._written_frames = 0
        self._deadline_ns = None
        self._limit_reached = threading.Event()

        # --- 初始化錄影檔案與狀態 --- #
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.fps = fps
        self.path = None
        self.dropped_frames = 0
        self.error = None

        # --- 初始化錄影佇列與背景執行緒 --- #
        self._queue = Queue(maxsize=8)
        self._stop = threading.Event()
        self._writer = None
        self._size = None

        self._thread = threading.Thread(
            target=self._run,
            name="VideoRecorder",
            daemon=True,
        )
        self._thread.start()

    # ---------------------------- 提交錄影影格 ---------------------------- #
    def submit(self, frame: np.ndarray) -> bool:

        # --- 檢查錄影狀態與影格格式 --- #
        if self.error is not None or self._limit_reached.is_set():
            return False
        if self._stop.is_set():
            raise RuntimeError("VideoRecorder 已關閉")
        if (frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3
                or frame.shape[0] == 0 or frame.shape[1] == 0):
            raise ValueError("錄影影格必須為非空 uint8 BGR")
        if frame.shape[0] % 2 or frame.shape[1] % 2:
            raise ValueError("MP4 錄影寬高必須為偶數")

        # --- 檢查最大錄影時間 --- #
        submitted_ns = time.monotonic_ns()
        if self._deadline_ns is None:
            self._deadline_ns = submitted_ns + round(self.max_minutes * 60 * 1e9)
        if submitted_ns >= self._deadline_ns:
            self._limit_reached.set()
            return False

        # --- 將影格放入佇列, 滿載時丟棄最舊影格 --- #
        sample = (frame.copy(), submitted_ns)
        try:
            self._queue.put_nowait(sample)
        except Full:
            try:
                self._queue.get_nowait()
                self.dropped_frames += 1
            except Empty:
                pass
            try:
                self._queue.put_nowait(sample)
            except Full:
                self.dropped_frames += 1

        return True

    # ---------------------------- 建立 MP4 檔案 ---------------------------- #
    def _open(self, size):

        # 釋放舊的 VideoWriter, 避免錄影檔案未完成封存
        if self._writer is not None:
            self._writer.release()

        # 使用時間戳記與 UUID 建立唯一檔案名稱
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = self.directory / f"record_{stamp}_{uuid4().hex[:8]}.mp4"

        self._writer = cv2.VideoWriter(
            str(self.path), cv2.VideoWriter_fourcc(*"mp4v"), self.fps, size,
        )

        if not self._writer.isOpened():
            raise RuntimeError(f"無法建立 MP4 錄影：{self.path}")

        self._size = size
        logging.getLogger(__name__).info("錄影檔案：%s", self.path)

    # -------------------------- 寫入影格與上限檢查 -------------------------- #
    def _write_limited(self, frame) -> bool:

        # 檢查最大影格數與錄影截止時間
        if (self._written_frames >= self._max_frames
                or time.monotonic_ns() >= self._deadline_ns):
            self._limit_reached.set()
            return False

        self._writer.write(frame)
        self._written_frames += 1

        if self._written_frames >= self._max_frames:
            self._limit_reached.set()

        return True

    # ---------------------------- 背景錄影執行緒 ---------------------------- #
    def _run(self):
        previous = None
        origin_ns = 0
        last_slot = -1

        try:
            while not self._stop.is_set() or not self._queue.empty():

                # --- 檢查錄影上限 --- #
                if (self._limit_reached.is_set() or (
                    self._deadline_ns is not None
                    and time.monotonic_ns() >= self._deadline_ns
                )):
                    self._limit_reached.set()
                    break

                # --- 從佇列取得影格 --- #
                try:
                    frame, submitted_ns = self._queue.get(timeout=0.1)
                except Empty:
                    continue

                # --- 解析度改變時建立新影片 --- #
                size = (frame.shape[1], frame.shape[0])
                if size != self._size:
                    self._open(size)
                    origin_ns, previous, last_slot = submitted_ns, None, -1

                # --- 根據提交時間計算影格位置 --- #
                slot = int((submitted_ns - origin_ns) * self.fps / 1_000_000_000)
                if slot <= last_slot:
                    continue

                # --- 使用上一幀補足時間軸, 避免低 FPS 造成影片快轉 --- #
                for _ in range(last_slot + 1, slot):
                    if not self._write_limited(previous):
                        break

                if self._limit_reached.is_set():
                    break

                # --- 寫入目前影格 --- #
                if not self._write_limited(frame):
                    break

                previous, last_slot = frame, slot

        except Exception as exc:
            self.error = exc
            logging.getLogger(__name__).error(
                "錄影已停止，串流不受影響：%s", exc
            )

        finally:
            # --- 釋放 VideoWriter 並封存 MP4 --- #
            if self._writer is not None:
                self._writer.release()

            # --- 達到錄影上限時清空佇列 --- #
            if self._limit_reached.is_set():
                while True:
                    try:
                        self._queue.get_nowait()
                    except Empty:
                        break

                logging.getLogger(__name__).warning(
                    "已達錄影上限 %g 分鐘，停止錄影並封存檔案",
                    self.max_minutes,
                )

    # ----------------------------- 關閉資源 ----------------------------- #
    def close(self):
        self._stop.set()
        self._thread.join(timeout=10.0)

        if self._thread.is_alive():
            logging.getLogger(__name__).warning(
                "錄影關閉等待超過 10 秒, MP4 可能尚未封存完成"
            )
        elif self.dropped_frames:
            logging.getLogger(__name__).warning(
                "錄影佇列丟棄 %d 幀，缺少畫面以重複上一幀補足時間軸",
                self.dropped_frames,
            )