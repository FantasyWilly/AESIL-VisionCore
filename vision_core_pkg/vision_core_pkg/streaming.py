#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File    : streaming.py
Author  : FantasyWilly
Email   : bc697522h04@gmail.com
SPDX-License-Identifier: Apache-2.0 

功能總覽:
    • 影像串流輸出器 (GStreamer / FFmpeg)
    • 預設採用 GStreamer
    • RTSP 輸出 -> MediaMTX

遵循:
    • Google Python Style Guide (含區段標題)
    • PEP 8 (行寬 ≤ 88, snake_case, 2 空行區段分隔)
"""

# ------------------------------------------------------------------------------------ #
# Import
# ------------------------------------------------------------------------------------ #
# 標準庫
import os
import re
from fractions import Fraction
import select
import subprocess
import threading
import time
from queue import Empty, Full, Queue
from typing import Optional
from dataclasses import dataclass

# 第三方套件
import numpy as np

# ROS 2 Python API
from rclpy.node import Node
from rclpy.logging import get_logger

# 專案模組
from vision_core_pkg.h264_sei import insert_timestamp


# ------------------------------------------------------------------------------------ #
# StreamingConfig 串流參數設定
# ------------------------------------------------------------------------------------ #
@dataclass
class StreamingConfig:
    """
    影像串流器參數設定

    args:
        • server_url        - 串流伺服器 URL
        • server_fps        - 串流影格率
        • server_bitrate    - 串流位元速率
    """
    
    server_url: str = "rtsp://127.0.0.1:8554/live/stream"
    server_fps: int = 30
    server_bitrate: str = "2M"

    @classmethod
    def from_node(cls, node: Node) -> "StreamingConfig":
        # --- 宣告參數 --- #
        node.declare_parameter("server_url", "rtsp://127.0.0.1:8554/live/stream")
        node.declare_parameter("server_fps", 30)
        node.declare_parameter("server_bitrate", "2M")

        # --- 讀取參數 --- #
        server_url          = node.get_parameter("server_url").value
        server_fps          = node.get_parameter("server_fps").value
        server_bitrate      = node.get_parameter("server_bitrate").value

        cfg = cls(
            server_url          = server_url,
            server_fps          = server_fps,
            server_bitrate      = server_bitrate,
        )

        log = node.get_logger().info
        log(f"[YAML]: Streaming Config")
        log(f"[Param] server_url            : {cfg.server_url}")
        log(f"[Param] server_fps            : {cfg.server_fps}")
        log(f"[Param] server_bitrate        : {cfg.server_bitrate}")
        log("-------------------------------------------------------------------------")

        return cfg


# ------------------------------------------------------------------------------------ #
# 影像串流輸出器 (FFmpeg) -> MediaMTX
# ------------------------------------------------------------------------------------ #
class _FFmpegStreaming:
    """
    FFmpeg 影像串流 [發布器]

    功能總覽:
        • 初始化 FFmpeg 串流發布參數
        • 建立 FFmpeg 子程序與影像輸入管道
        • 將 BGR 影像轉換為 H.264 並發布至 RTSP
        • 採用非阻塞式 I/O 寫入影格
        • 處理影格寫入逾時與管道異常
        • 管理執行緒同步與 FFmpeg 資源釋放
    """

    def __init__(
        self, 
        rtsp_url: str, 
        fps: int = 30, 
        bitrate: str = "2M"
    ):
        # --------------------------------------------------------------
        # 初始化串流發布參數
        # rtsp_url - RTSP / MediaMTX 伺服器位址
        # fps      - 影像串流影格率
        # bitrate  - H.264 編碼目標位元率
        # --------------------------------------------------------------
        self.rtsp_url, self.fps, self.bitrate = rtsp_url, fps, bitrate

        # --------------------------------------------------------------
        # 初始化串流發布器狀態
        # ffmpeg - 存放 FFmpeg 子程序物件
        # lock   - 互斥鎖，避免多個執行緒同時操作 FFmpeg
        # size   - 記錄影像尺寸, 用於檢查輸入影格
        # --------------------------------------------------------------
        self.ffmpeg: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._size = None

    # ------------------------- 啟動 FFmpeg 串流 ------------------------- #
    def start(self, width: int, height: int) -> None:

        if width <= 0 or height <= 0 or width % 2 or height % 2:
            raise ValueError("yuv420p 輸出寬高必須為正偶數")

        with self._lock:
            self._stop_locked()
            args = [
                "ffmpeg", "-hide_banner", "-loglevel", "warning",
                "-f", "rawvideo", "-pix_fmt", "bgr24",
                "-s", f"{width}x{height}", "-r", str(self.fps), "-i", "-",
                "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
                "-b:v", self.bitrate, "-maxrate", self.bitrate,
                "-bufsize", self.bitrate, "-pix_fmt", "yuv420p",
                "-g", str(self.fps), "-an", "-f", "rtsp", self.rtsp_url,
            ]
            self.ffmpeg = subprocess.Popen(
                args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=None, bufsize=0,
            )
            try:
                os.set_blocking(self.ffmpeg.stdin.fileno(), False)
            except BaseException:
                self._stop_locked()
                raise
            self._size = (width, height)

    # ------------------------- 寫入影格至 FFmpeg ------------------------- #
    def write_frame(self, frame: np.ndarray) -> None:
        with self._lock:
            if self.ffmpeg is None or self.ffmpeg.poll() is not None:
                self._stop_locked()
                raise BrokenPipeError("FFmpeg 未啟動或已退出, 請重新 start()")
            width, height = self._size
            if frame.dtype != np.uint8 or frame.shape != (height, width, 3):
                raise ValueError("影格必須是 uint8 BGR, 且尺寸與 start() 相同")
            remaining = memoryview(frame.tobytes())
            deadline = time.monotonic() + 2.0
            fd = self.ffmpeg.stdin.fileno()
            try:
                while remaining:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("FFmpeg 寫入逾時")
                    if not select.select([], [fd], [], 0.1)[1]:
                        continue
                    try:
                        count = os.write(fd, remaining)
                    except BlockingIOError:
                        continue
                    if count == 0:
                        raise BrokenPipeError("FFmpeg pipe closed")
                    remaining = remaining[count:]
            except BaseException:
                self._stop_locked()
                raise

    # ------------------------- 停止 FFmpeg 子程序 ------------------------ #
    def _stop_locked(self):
        process, self.ffmpeg = self.ffmpeg, None
        self._size = None
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        finally:
            if process.stdin is not None:
                process.stdin.close()

    # ------------------------- 關閉 FFmpeg 串流 ------------------------- #
    def stop(self) -> None:
        with self._lock:
            self._stop_locked()


# ------------------------------------------------------------------------------------ #
# GStreamer H.264 編碼 -> 每幀插入 SEI -> RTSP / MediaMTX
# ------------------------------------------------------------------------------------ #
class _GStreamerStreaming:
    """
    GStreamer 影像串流 [發布器]

    功能總覽:
        • 初始化 GStreamer 與串流參數
        • 將 BGR 原始影像轉換為 H.264
        • 管理影格時間戳記 (PTS / DTS)
        • 將接收時間與影格序號寫入 SEI
        • 透過 RTSP / TCP 發布至 MediaMTX
        • 檢查管線狀態與釋放串流資源
    """

    def __init__(
        self,
        rtsp_url: str,
        fps: float = 30,
        bitrate: str = "2M",
    ):
        
        # --- 初始化 GStreamer --- #
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        Gst.init(None)
        self.Gst = Gst

        # --- 初始化 RTSP 伺服器與影格率 --- #
        self.rtsp_url = rtsp_url
        self.rate = Fraction(str(fps)).limit_denominator(1001)

        # --- 解析 Bitrate 並轉換為 x264enc 使用的 kbps --- #
        match = re.fullmatch(
            r"\s*(\d+(?:\.\d+)?)\s*([kKmM]?)\s*",
            str(bitrate),
        )

        if match is None:
            raise ValueError("bitrate 格式應為 2M, 2000k 或每秒位元數")

        bits = float(match[1]) * {
            "": 1,
            "k": 1000,
            "m": 1000000,
        }[match[2].lower()]

        self.bitrate_kbps = round(bits / 1000)

        if not 1 <= self.bitrate_kbps <= 2048000:
            raise ValueError("bitrate 超出 x264enc 可用範圍")

        # --- 初始化編碼與發布管線 --- #
        self.encoder = self.publisher = None
        self._size = None

        # --- 初始化影格序號與執行緒取消事件 --- #
        self._sequence = 0
        self._cancel = threading.Event()

    # ------------------------- 建立 RTSP 發布管線 ------------------------- #
    def _create_publisher(self):

        # H.264 AppSrc -> H.264 Parser -> RTSP Client Sink
        pipeline = self.Gst.parse_launch(
            "appsrc name=encoded is-live=true format=time block=false "
            "max-buffers=2 max-bytes=0 ! h264parse ! "
            "rtspclientsink name=rtsp protocols=tcp latency=0 "
            "tcp-timeout=3000000"
        )

        # 設定 RTSP / MediaMTX 伺服器位址
        pipeline.get_by_name("rtsp").set_property(
            "location", self.rtsp_url
        )

        return pipeline

    # ----------------------- 啟動 GStreamer 串流 ------------------------ #
    def start(self, width: int, height: int) -> None:

        # --- 檢查 I420 影像尺寸是否合法 --- #
        if width <= 0 or height <= 0 or width % 2 or height % 2:
            raise ValueError("I420 輸出寬高必須為正偶數")

        # --- 關閉既有管線並釋放資源 --- #
        self.stop()
        self._cancel.clear()
        Gst = self.Gst

        try:
            # --- 建立 H.264 低延遲編碼管線 --- #
            # BGR -> I420 -> H.264 Encoder -> H.264 Parser -> AppSink
            self.encoder = Gst.parse_launch(
                "appsrc name=raw is-live=true format=time block=false "
                "max-buffers=2 max-bytes=0 ! videoconvert ! "
                "video/x-raw,format=I420 ! "
                f"x264enc tune=zerolatency speed-preset=ultrafast bframes=0 "
                f"bitrate={self.bitrate_kbps} "
                f"key-int-max={max(1, round(float(self.rate)))} ! "
                "h264parse ! "
                "video/x-h264,stream-format=byte-stream,alignment=au ! "
                "appsink name=au sync=false max-buffers=2 drop=false "
                "enable-last-sample=false"
            )

            # --- 取得原始影像輸入端並設定影像規格 --- #
            self.raw_source = self.encoder.get_by_name("raw")

            self.raw_source.set_property(
                "caps",
                Gst.Caps.from_string(
                    f"video/x-raw,format=BGR,width={width},height={height},"
                    f"framerate={self.rate.numerator}/{self.rate.denominator}"
                )
            )

            # --- 取得 H.264 編碼結果輸出端 --- #
            self.encoded_sink = self.encoder.get_by_name("au")

            # --- 建立 RTSP 發布管線與 H.264 輸入端 --- #
            self.publisher = self._create_publisher()
            self.encoded_source = self.publisher.get_by_name("encoded")

            # --- 初始化影像尺寸與時間戳記資訊 --- #
            self._size = (width, height)
            self._origin_ns = None
            self._last_pts = -1
            self._encoder_pts_offset = None

            # --- 啟動 RTSP 發布與 H.264 編碼管線 --- #
            for pipeline in (self.publisher, self.encoder):
                if pipeline.set_state(Gst.State.PLAYING) == \
                        Gst.StateChangeReturn.FAILURE:
                    raise RuntimeError("GStreamer 無法啟動管線")

            # --- 檢查 GStreamer 管線狀態 --- #
            self._check_errors()

        except Exception:
            self.stop()
            raise

    # ----------------------- 檢查 GStreamer 管線狀態 ---------------------- #
    def _check_errors(self):

        # --- 檢查是否收到串流取消指令 --- #
        if self._cancel.is_set():
            raise RuntimeError("串流正在關閉")

        # --- 檢查編碼與發布管線的 Bus 訊息 --- #
        for pipeline in (self.encoder, self.publisher):
            if pipeline is None:
                continue

            message = pipeline.get_bus().timed_pop_filtered(
                0,
                self.Gst.MessageType.ERROR | self.Gst.MessageType.EOS,
            )

            # --- 處理 GStreamer 錯誤與串流結束事件 --- #
            if message is not None:
                if message.type == self.Gst.MessageType.ERROR:
                    error, debug = message.parse_error()
                    raise RuntimeError(f"GStreamer: {error}; {debug}")

                raise RuntimeError("GStreamer 串流提前結束")

    # ------------------------ 編碼並發布單幀影像 ------------------------ #
    def write_frame(
        self,
        frame: np.ndarray,
        received_ns: int | None = None,
    ) -> None:
        """
        將單幀 BGR 影像進行 H.264 編碼, 插入 SEI 並發布至 RTSP

        args:
            frame: 原始 BGR 影像
            received_ns: 影格接收時的 Unix 奈秒時間戳記
        """

        # --- 檢查管線是否已啟動 --- #
        if self._size is None:
            raise RuntimeError("GStreamer 尚未 start")

        width, height = self._size

        # --- 檢查輸入影像尺寸與資料格式 --- #
        if frame.dtype != np.uint8 or frame.shape != (height, width, 3):
            raise ValueError("影格必須是與 start 尺寸相同的 uint8 BGR")

        # --- 檢查影格接收時間戳記是否合法 --- #
        if received_ns is not None and (
            not isinstance(received_ns, int)
            or not 0 < received_ns < 2**64
        ):
            raise ValueError("received_ns 必須為有效的 Unix 奈秒整數")

        Gst = self.Gst
        self._check_errors()

        # --- RTSP 發送佇列流量控制, 避免影格持續堆積 --- #
        deadline = time.monotonic() + 2.0

        while self.encoded_source.get_property(
            "current-level-buffers"
        ) >= 2:
            self._check_errors()

            if time.monotonic() >= deadline:
                raise TimeoutError("RTSP 發送佇列堵塞超過 2 秒")

            time.sleep(0.01)

        # --- 計算影格 PTS 與播放時間長度 --- #
        now = time.monotonic_ns()

        if self._origin_ns is None:
            self._origin_ns = now

        # 確保 PTS 持續遞增 & 根據 FPS 計算單幀播放時間 (ns)
        pts = max(now - self._origin_ns, self._last_pts + 1)
        duration = round(Gst.SECOND / float(self.rate))

        # --- BGR 影像記憶體對齊 (4 Bytes Alignment) --- #
        stride = (width * 3 + 3) // 4 * 4

        if stride == width * 3:
            data = frame.tobytes()
        else:
            packed = np.zeros((height, stride), dtype=np.uint8)
            packed[:, :width * 3] = frame.reshape(height, width * 3)
            data = packed.tobytes()

        # --- 建立 GStreamer Buffer --- #
        raw = Gst.Buffer.new_wrapped(data)

        raw.pts = pts
        raw.duration = duration

        # --- 將 BGR 影像送入 H.264 編碼管線 --- #
        if self.raw_source.emit("push-buffer", raw) != Gst.FlowReturn.OK:
            raise RuntimeError("GStreamer 無法送入原始影格")

        # --- 等待 H.264 編碼結果並進行逾時檢查 --- #
        sample = None
        deadline = time.monotonic() + 2.0

        while sample is None:
            self._check_errors()

            sample = self.encoded_sink.emit(
                "try-pull-sample", Gst.SECOND // 10
            )

            if sample is None and time.monotonic() >= deadline:
                raise TimeoutError("H.264 編碼等待超過 2 秒")

        # --- 取得 H.264 編碼後的影格 --- #
        encoded = sample.get_buffer()

        if encoded.pts == Gst.CLOCK_TIME_NONE:
            raise RuntimeError("編碼器未提供 PTS, 無法確認影格配對")

        # --- 驗證編碼前後的 PTS, 避免 SEI 與影格配對錯誤 --- #
        offset = int(encoded.pts) - pts

        if self._encoder_pts_offset is None:
            self._encoder_pts_offset = offset

        if offset != self._encoder_pts_offset:
            raise RuntimeError(
                "編碼影格 PTS 不符, 停止發送以免 SEI 配錯幀"
            )

        # --- 提取 H.264 位元流並插入 SEI 資訊 --- #
        data = encoded.extract_dup(0, encoded.get_size())

        if received_ns is not None:
            data = insert_timestamp(
                data,
                self._sequence,
                received_ns,
            )

        # --- 建立含 SEI 資訊的 H.264 Gst.Buffer --- #
        output = Gst.Buffer.new_wrapped(data)

        output.pts = output.dts = pts
        output.duration = duration
        output.set_flags(encoded.get_flags())

        # --- 同步 H.264 編碼與發布管線的 Caps --- #
        self.encoded_source.set_property("caps", sample.get_caps())

        # --- 將 H.264 影格發布至 RTSP / MediaMTX --- #
        if self.encoded_source.emit(
            "push-buffer", output
        ) != Gst.FlowReturn.OK:
            raise RuntimeError("GStreamer 無法送出 H.264 影格")

        # --- 更新影格時間戳記與序號 --- #
        self._last_pts = pts
        self._sequence += 1

        # --- 確認影格發布後的管線狀態 --- #
        self._check_errors()

    # --------------------------- 發送串流取消訊號 --------------------------- #
    def cancel(self) -> None:
        self._cancel.set()

    # --------------------------- 關閉管線並釋放資源 -------------------------- #
    def stop(self) -> None:

        # --- 將 GStreamer 管線切換至 NULL 並清除物件 --- #
        for name in ("encoder", "publisher"):
            pipeline = getattr(self, name)

            if pipeline is not None:
                pipeline.set_state(self.Gst.State.NULL)
                setattr(self, name, None)

        # --- 重置影像尺寸 --- #
        self._size = None


# ------------------------------------------------------------------------------------ #
# FFmpeg 推流主程式
# ------------------------------------------------------------------------------------ #
class FFmpegVideoOutput:
    """
    FFmpeg 影像串流輸出 [管理器]

    功能總覽:
        • 初始化 FFmpeg 串流參數與發布器
        • 使用 Queue 管理最新影格
        • 使用背景執行緒進行影像編碼與推流
        • 根據影像尺寸自動建立或重啟串流管線
        • 處理 RTSP 串流異常與自動重新連線
        • 管理背景執行緒與 FFmpeg 資源釋放
    """

    def __init__(
        self, 
        url: str = "rtsp://127.0.0.1:8554/live/stream", 
        fps: int = 30, 
        bitrate: str = "2M"
    ):
        
        # --- 檢查 FPS 參數 --- #
        if not np.isfinite(fps) or fps <= 0:
            raise ValueError("fps 必須為有限正數")

        # --------------------------------------------------------------
        # 初始化串流參數
        # url     - RTSP / MediaMTX 伺服器位址
        # fps     - 影像串流影格率
        # bitrate - H.264 編碼目標位元率
        # --------------------------------------------------------------
        self.url = url
        self.fps = fps
        self.bitrate = bitrate

        # --------------------------------------------------------------
        # 初始化串流輸出狀態
        # queue      - 存放最新影格, 最大容量為 1
        # stop_event - 用於通知背景執行緒停止運作
        # --------------------------------------------------------------
        self.queue = Queue(maxsize=1)
        self.stop_event = threading.Event()

        # --------------------------------------------------------------
        # 初始化 FFmpeg 串流發布器
        # streamer - 負責 H.264 編碼與 RTSP 發布
        # size     - 記錄目前串流影像尺寸, 用於判斷是否重啟串流
        # --------------------------------------------------------------
        self.streamer = _FFmpegStreaming(url, fps, bitrate)
        self.size = None

        # --- 建立並啟動背景推流執行緒 --- #
        self.thread = threading.Thread(
            target=self._run,
            name="VideoOutput",
            daemon=True,
        )
        self.thread.start()

    # ----------------------------- 接收影像 ----------------------------- #
    def submit(self, frame: np.ndarray) -> None:
        if self.stop_event.is_set():
            raise RuntimeError("VideoOutput 已關閉")

        try:
            self.queue.get_nowait()
        except Empty:
            pass

        try:
            self.queue.put_nowait(frame.copy())
        except Full:
            pass

    # --------------------------- 關閉 FFmpeg -------------------------- #
    def _close_process(self):
        self.streamer.stop()
        self.size = None

    # ----------------------------- 寫入影像 ----------------------------- #
    def _write(self, frame: np.ndarray):
        height, width = frame.shape[:2]

        if self.size != (width, height):
            self.streamer.start(width, height)
            self.size = (width, height)

        self.streamer.write_frame(frame)

    # ---------------------------- 背景推流執行緒 --------------------------- #
    def _run(self):
        try:
            while not self.stop_event.is_set():

                try:
                    frame = self.queue.get(timeout=0.1)
                except Empty:
                    continue

                if self.stop_event.is_set():
                    break

                try:
                    self._write(frame)

                except (OSError, ValueError) as exc:
                    get_logger("VideoOutput").error(
                        f"RTSP 輸出失敗, 將重新連線: {exc}"
                    )
                    self._close_process()
                    self.stop_event.wait(1.0)

        finally:
            self._close_process()

    # --------------------------- 關閉背景推流執行緒 -------------------------- #
    def close(self):
        self.stop_event.set()
        self.thread.join()


# ------------------------------------------------------------------------------------ #
# GStreamer 推流主程式
# ------------------------------------------------------------------------------------ #
class GStreamerVideoOutput:
    """
    影像串流輸出 [管理器]

    功能總覽:
        • 初始化影像串流參數與 GStreamer 發布器
        • 使用 Queue 管理最新影格與接收時間戳記
        • 使用背景執行緒進行影像編碼與推流
        • 根據影像尺寸自動建立或重啟串流管線
        • 處理 RTSP 串流異常與自動重新連線
        • 管理背景執行緒與串流資源釋放
    """

    def __init__(
        self, 
        url: str = "rtsp://127.0.0.1:8554/live/stream", 
        fps: int = 30, 
        bitrate: str = "2M"
    ):
        
        # --- 檢查 FPS 參數 --- #
        if not np.isfinite(fps) or fps <= 0:
            raise ValueError("fps 必須為有限正數")

        # --------------------------------------------------------------
        # 初始化串流參數
        # url     - RTSP / MediaMTX 伺服器位址
        # fps     - 影像串流影格率
        # bitrate - H.264 編碼目標位元率
        # --------------------------------------------------------------
        self.url = url
        self.fps = fps
        self.bitrate = bitrate

        # --------------------------------------------------------------
        # 初始化串流輸出狀態
        # queue      - 存放最新影格與接收時間戳記, 最大容量為 1
        # stop_event - 用於通知背景執行緒停止運作
        # --------------------------------------------------------------
        self.queue = Queue(maxsize=1)
        self.stop_event = threading.Event()

        # --------------------------------------------------------------
        # 初始化 GStreamer 串流發布器
        # streamer - 負責 H.264 編碼, SEI 插入與 RTSP 發布
        # size     - 記錄目前串流影像尺寸, 用於判斷是否重建管線
        # --------------------------------------------------------------
        self.streamer = _GStreamerStreaming(url, fps, bitrate)
        self.size = None

        # --- 建立並啟動背景推流執行緒 --- #
        self.thread = threading.Thread(
            target=self._run,
            name="VideoOutput",
            daemon=True,
        )
        self.thread.start()

    # ------------------------ 接收影像與時間戳記 ------------------------ #
    def submit(
        self, 
        frame: np.ndarray, 
        received_ns: int | None = None,
    ) -> None:

        if self.stop_event.is_set():
            raise RuntimeError("VideoOutput 已關閉")
        if received_ns is not None and (
            not isinstance(received_ns, int) or not 0 < received_ns < 2**64
        ):
            raise ValueError("received_ns 必須為有效的 Unix 奈秒整數")

        try:
            self.queue.get_nowait()
        except Empty:
            pass

        try:
            self.queue.put_nowait((frame.copy(), received_ns))
        except Full:
            pass

    # ---------------------------- 關閉串流管線 ---------------------------- #
    def _close_process(self):
        self.streamer.stop()
        self.size = None

    # --------------------------- 編碼並發布影格 ---------------------------- #
    def _write(self, frame: np.ndarray, received_ns: int | None = None):

        height, width = frame.shape[:2]

        if self.size != (width, height):
            self.streamer.start(width, height)
            self.size = (width, height)

        self.streamer.write_frame(frame, received_ns)

    # --------------------------- 背景推流執行緒 ---------------------------- #
    def _run(self):
        try:
            while not self.stop_event.is_set():
                try:
                    frame, received_ns = self.queue.get(timeout=0.1)
                except Empty:
                    continue

                if self.stop_event.is_set():
                    break

                try:
                    self._write(frame, received_ns)
                except Exception as exc:
                    if self.stop_event.is_set():
                        break
                    get_logger("VideoOutput").error(f"RTSP 輸出失敗, 將重新連線: {exc}")
                    self._close_process()
                    self.stop_event.wait(1.0)

        finally:
            self._close_process()

    # --------------------------- 關閉背景推流執行緒 -------------------------- #
    def close(self):
        self.stop_event.set()
        self.streamer.cancel()
        self.thread.join(timeout=3.0)

        if self.thread.is_alive():
            get_logger(
                f"[cleanup] 串流執行緒 3 秒內未結束, 可能卡在 GStreamer 原生關閉呼叫",
                f"停止等待, 繼續釋放相機與 ROS 資源"
            )
