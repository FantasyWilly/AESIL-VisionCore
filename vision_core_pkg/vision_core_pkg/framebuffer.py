#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
File    : framebuffer.py
Author  : FantasyWilly
Email   : bc697522h04@gmail.com
SPDX-License-Identifier: Apache-2.0 

功能總覽:
    • 讀取影像來源的最新影格
    • 支援 RTSP, GStreamer, UDP, MIPI, HDMI 擷取卡與 Webcam 來源

遵循:
    • Google Python Style Guide (含區段標題)
    • PEP 8 (行寬 ≤ 88, snake_case, 2 空行區段分隔)
"""

# ------------------------------------------------------------------------------------ #
# Import
# ------------------------------------------------------------------------------------ #
# 標準庫
import threading
import time
from queue import Empty, Full, Queue
from typing import Optional
from dataclasses import dataclass

# 第三方套件
import cv2
import numpy as np

# ROS 2 Python API
from rclpy.node import Node


# ------------------------------------------------------------------------------------ #
# FrameBufferConfig 讀取影像參數設定
# ------------------------------------------------------------------------------------ #
@dataclass
class FrameBufferConfig:
    """
    影像讀取器參數設定

    args:
        • camera_source     - 相機來源
        • camera_width      - 影像寬度
        • camera_height     - 影像高度
    """
    camera_source: str
    camera_width: int
    camera_height: int

    @classmethod
    def from_node(cls, node: Node) -> "FrameBufferConfig":
        # --- 宣告參數 --- #
        node.declare_parameter("camera_source", "/tmp/streaming.sock")
        node.declare_parameter("camera_width", 1280)
        node.declare_parameter("camera_height", 720)

        # --- 讀取參數 --- #
        camera_source           = node.get_parameter("camera_source").value
        camera_width            = node.get_parameter("camera_width").value
        camera_height           = node.get_parameter("camera_height").value

        cfg = cls(
            camera_source       = camera_source,
            camera_width        = camera_width,
            camera_height       = camera_height,
        )

        log = node.get_logger().info
        log(f"[YAML]: FrameBuffer Config")
        log(f"[Param] camera_source         : {cfg.camera_source}")
        log(f"[Param] camera_width          : {cfg.camera_width}")
        log(f"[Param] camera_height         : {cfg.camera_height}")
        log("-------------------------------------------------------------------------")

        return cfg


# ------------------------------------------------------------------------------------ #
# 僅保留最新影格的接收器
# ------------------------------------------------------------------------------------ #
class _GStreamerCapture:
    """
    使用原生 GStreamer API 接收影像, 提供類似 cv2.VideoCapture 的操作介面

    功能總覽:
        • 建立並啟動 GStreamer 影像接收管線
        • 透過 appsink 取得解碼後的 BGR 影格
        • 使用 GstVideo.VideoInfo 取得實際影像記憶體配置
        • 根據 stride 與 offset 正確解析影像資料
        • 將 Gst.Buffer 複製為獨立的 NumPy 陣列
        • 監控 GStreamer 錯誤與串流結束事件
        • 關閉 Pipeline 並釋放相關資源
    """
    def __init__(self, pipeline_text: str):
        import gi
        gi.require_version("Gst", "1.0")
        gi.require_version("GstVideo", "1.0")
        from gi.repository import Gst, GstVideo

        Gst.init(None)
        self.Gst, self.GstVideo = Gst, GstVideo
        self.pipeline = None
        try:
            self.pipeline = Gst.parse_launch(pipeline_text.replace(
                "appsink ", "appsink name=framebuffer_sink ", 1,
            ))
            self.sink = self.pipeline.get_by_name("framebuffer_sink")
            if self.sink is None:
                raise RuntimeError("接收管線需包含 BGR appsink")
            self.bus = self.pipeline.get_bus()
            if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError("GStreamer 無法開啟接收管線")
        except BaseException:
            self.release()
            raise

    # ---------------------------- 檢查接收器狀態 --------------------------- #
    def isOpened(self):
        return self.pipeline is not None

    # ---------------------- 讀取 GStreamer BGR 影格 --------------------- #
    def read(self):
        sample = self.sink.emit("try-pull-sample", self.Gst.SECOND // 2)
        message = self.bus.pop_filtered(self.Gst.MessageType.ERROR | self.Gst.MessageType.EOS)
        if message is not None:
            if message.type == self.Gst.MessageType.ERROR:
                error, debug = message.parse_error()
                raise RuntimeError(f"GStreamer 接收失敗：{error}; {debug}")
            raise RuntimeError("GStreamer 影像來源結束")
        if sample is None:
            return False, None
        info = self.GstVideo.VideoInfo.new_from_caps(sample.get_caps())
        if info.finfo.name != "BGR":
            raise RuntimeError("GStreamer appsink 必須輸出 BGR")
        buffer = sample.get_buffer()
        data = buffer.extract_dup(0, buffer.get_size())
        # 使用實際 stride，去除列尾對齊；複製後可安全釋放 Gst sample。
        frame = np.ndarray(
            (info.height, info.width, 3), dtype=np.uint8, buffer=data,
            offset=info.offset[0], strides=(info.stride[0], 3, 1),
        ).copy()
        return True, frame

    # ------------------------ 釋放 GStreamer 資源 ----------------------- #
    def release(self):
        if self.pipeline is not None:
            self.pipeline.set_state(self.Gst.State.NULL)
            self.pipeline = None


# ------------------------------------------------------------------------------------ #
# 僅保留最新影格的接收器
# ------------------------------------------------------------------------------------ #
class _LatestFrameBuffer:
    """
    使用背景執行緒持續接收影像, 並只保留最新一張影格

    功能總覽:
        • 支援 RTSP, RTP/H.264 UDP 與 GStreamer SHM 影像來源
        • 支援 OpenCV FFmpeg 與 GStreamer 接收後端
        • 當 OpenCV 缺少 GStreamer 後端時, 使用原生 GStreamer
        • 使用獨立執行緒持續讀取並解碼影像
        • 使用容量為 1 的 Queue 保留最新影格
        • 提供純影像讀取與附帶接收時間戳記的讀取介面
        • 驗證影像格式與解析度
        • 支援來源開啟重試, 讀取逾時與資源釋放
    """
    # --------------------------- 初始化影像接收器 --------------------------- #
    def _start(self, src, timeout, retry, backend, expected_size=None):

        # --- 檢查參數設定 --- #
        if timeout <= 0 or retry < 1:
            raise ValueError("timeout 必須大於 0, retry 必須至少為 1")

        if backend not in (cv2.CAP_FFMPEG, cv2.CAP_GSTREAMER):
            raise ValueError("逾時控制僅支援 CAP_FFMPEG / CAP_GSTREAMER")

        native_gstreamer = (
            backend == cv2.CAP_GSTREAMER
            and not cv2.videoio_registry.hasBackend(backend)
        )
        if not native_gstreamer and not cv2.videoio_registry.hasBackend(backend):
            raise RuntimeError(f"目前 OpenCV 不支援 backend={backend}")

        # --------------------------------------------------------------
        # 初始化接收器狀態
        # stop  - 用於通知 reader 停止
        # queue - 用於存放最新影格, 最大容量為 1
        # error - 用於記錄 reader 執行緒的異常
        # size  - 用於記錄影格尺寸, 若指定 expected_size, 則檢查接收影格是否符合
        # cap   - 用於存放 cv2.VideoCapture 物件
        # --------------------------------------------------------------
        self._stop = threading.Event()
        self._queue = Queue(maxsize=1)
        self._error = None
        self._size = expected_size
        self._cap = None

        # --- 嘗試開啟來源, 若失敗則重試 retry 次 --- #
        last_error = None

        for attempt in range(1, retry + 1):
            cap = None

            try:
                if native_gstreamer:
                    cap = _GStreamerCapture(src)

                else:
                    cap = cv2.VideoCapture(
                        src,
                        backend,
                        [
                            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                            max(1, int(timeout * 1000)),
                            cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                            500,
                        ],
                    )

                if not cap.isOpened():
                    raise RuntimeError("影像接收器無法開啟")

                self._cap = cap
                break

            except Exception as exc:
                last_error = exc

                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass

                if attempt < retry:
                    time.sleep(0.5)

        if self._cap is None:
            raise RuntimeError(
                f"無法在 {retry} 次嘗試內開啟影像來源"
            ) from last_error

        # --- 啟動背景讀取執行緒, 將接收影格放入 Queue --- #
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

        # --- 等待實際影格, 確保尺寸已知, 保留第一幀供呼叫端使用 --- #
        try:
            sample = self.read_with_timestamp(timeout)
            if sample is None:
                raise RuntimeError("開啟來源後未在期限內收到第一幀")
            try:
                self._queue.put_nowait(sample)
            except Full:
                pass
        except BaseException:
            self.release()
            raise

    # -------------------- 持續讀取, 只保留最新一張, 結束時關閉來源 -------------------- #
    def _reader(self):
        try:
            while not self._stop.is_set():
                ok, frame = self._cap.read()
                if not ok:
                    self._stop.wait(0.01)
                    continue
                # 本接收端完成讀取／解碼的系統時間，不是上游拍攝時間。
                received_ns = time.time_ns()
                if frame.ndim != 3 or frame.shape[2] != 3:
                    raise RuntimeError("接收影像必須為三通道 BGR")
                size = (frame.shape[1], frame.shape[0])
                if self._size is not None and size != self._size:
                    raise RuntimeError(f"影像尺寸改變或與設定不符: {size} != {self._size}")
                self._size = size
                try:
                    self._queue.get_nowait()
                except Empty:
                    pass
                try:
                    self._queue.put_nowait((frame, received_ns))
                except Full:
                    pass
        except Exception as exc:
            self._error = exc
        finally:
            self._cap.release()

    # ----------------------------- 讀取影像 ----------------------------- #
    def read(self, timeout: float = 0.5) -> Optional[np.ndarray]:
        sample = self.read_with_timestamp(timeout)
        return None if sample is None else sample[0]

    # -------------------------- 讀取影像 + 時間戳 -------------------------- #
    def read_with_timestamp(
        self, timeout: float = 0.5,
    ) -> Optional[tuple[np.ndarray, int]]:
        if timeout < 0:
            raise ValueError("timeout 不可為負數")
        if self._stop.is_set():
            return None
        if self._error is not None:
            raise RuntimeError("影像接收執行緒失敗") from self._error
        try:
            sample = self._queue.get(timeout=timeout)
            if self._error is not None:
                raise RuntimeError("影像接收執行緒失敗") from self._error
            return None if self._stop.is_set() else sample
        except Empty:
            if self._error is not None:
                raise RuntimeError("影像接收執行緒失敗") from self._error
            return None

    # ---------------------------- 護取影格尺寸 ---------------------------- #
    def get_frame_size(self):
        return self._size

    # --------------------------- 關閉影像接收器 ---------------------------- #
    def release(self, timeout: float = 3.0) -> None:

        # 設定停止事件, 通知背景執行緒停止接收
        self._stop.set()
        thread = getattr(self, "_thread", None)

        # 如果背景執行緒已建立, 等待其結束
        if thread is not None:
            if threading.current_thread() is thread:
                raise RuntimeError("背景執行緒不可等待自己結束")

            # 等待背景執行緒完成讀取與資源釋放
            thread.join(timeout=timeout)

            # 若執行緒尚未停止, 避免強制跨執行緒釋放 Capture
            if thread.is_alive():
                raise RuntimeError(
                    f"影像接收執行緒未在 {timeout:g} 秒內停止, "
                    "不強制跨執行緒釋放 Capture"
                )

        # 清空 Queue 中尚未處理的影格
        while True:
            try:
                self._queue.get_nowait()

            except Empty:
                # Queue 已清空, 結束資源清理
                break


# ------------------------------------------------------------------------------------ #
# 接收 HDMI / Webcam 硬體裝置
# ------------------------------------------------------------------------------------ #
class V4L2FrameBuffer(_LatestFrameBuffer):
    """
    透過 GStreamer / V4L2 讀取本機影像裝置,
    轉換為 BGR 格式並提供最新影格

    args:
        device  - V4L2 裝置路徑
        width   - 影像擷取寬度
        height  - 影像擷取高度
        fps     - 影像擷取幀率
        fourcc  - 影像格式 (MJPG / YUYV / YUY2 / UYVY / NV12)
        timeout - 等待影像來源啟動的逾時時間 (秒)
        retry   - 影像來源開啟的最大嘗試次數
        backend - OpenCV 擷取後端 (GStreamer)
    """

    def __init__(
        self,
        device: str = "/dev/video0",
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        fourcc: str = "MJPG",
        timeout: float = 5.0,
        retry: int = 1,
        backend: int | None = None,
    ) -> None:

        # --- 檢查輸入參數 --- #
        if not isinstance(device, str) or not device.strip() or "\x00" in device:
            raise ValueError("device 必須為有效裝置路徑")

        for name, value in (
            ("width", width), ("height", height),
            ("fps", fps), ("retry", retry)
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} 必須為正整數")

        if not np.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout 必須為有限正數")

        if backend not in (None, cv2.CAP_ANY, cv2.CAP_GSTREAMER):
            raise ValueError("僅支援 GStreamer")

        # --- 設定影像格式 --- #
        formats = {
            "MJPG": None,
            "YUYV": "YUY2",
            "YUY2": "YUY2",
            "UYVY": "UYVY",
            "NV12": "NV12",
        }

        if not isinstance(fourcc, str) or fourcc.upper() not in formats:
            raise ValueError("不支援的影像格式")

        fmt = formats[fourcc.upper()]
        mode = f"width={width},height={height},framerate={fps}/1"

        source_caps = (
            f"image/jpeg,{mode} ! jpegdec"
            if fmt is None else
            f"video/x-raw,format={fmt},{mode}"
        )

        # --- 建立 GStreamer Pipeline --- #
        escaped = device.replace("\\", "\\\\").replace('"', '\\"')

        self._camera_source = (
            f'v4l2src device="{escaped}" ! {source_caps} ! '
            "videoconvert ! video/x-raw,format=BGR ! "
            "appsink max-buffers=1 drop=true sync=false enable-last-sample=false"
        )

        # --- 啟動影像擷取 --- #
        self._start(
            self._camera_source,
            timeout,
            retry,
            cv2.CAP_GSTREAMER,
            (width, height),
        )


# ------------------------------------------------------------------------------------ #
# 接收 RTSP 影像流
# ------------------------------------------------------------------------------------ #
class RTSPFrameBuffer(_LatestFrameBuffer):
    """
    使用 GStreamer 接收 RTSP H.264 影像流

    功能總覽:
        • 使用 TCP 接收 RTSP H.264 影像
        • 使用 GStreamer 解碼並轉換為 BGR 格式
        • 使用 appsink 限制緩衝影格數量
        • 透過 _LatestFrameBuffer 持續接收並保留最新影格
        • 支援影像來源開啟逾時與重試機制

    args:
        src     - RTSP 影像來源位址
        timeout - 等待第一張影格的最長時間, 單位為秒
        retry   - 開啟影像來源的最大嘗試次數
    """

    def __init__(
        self,
        src: str,
        timeout: float = 5.0,
        retry: int = 1,
    ) -> None:

        # --- RTSP 接收設定 --- #
        # 使用 TCP 傳輸 RTSP 影像
        protocol = "tcp"

        # 設定 RTSP 接收緩衝延遲, 單位為毫秒
        latency = 100

        # 跳脫 RTSP URL 中的特殊字元, 避免破壞 Pipeline 字串格式
        escaped = src.replace("\\", "\\\\").replace('"', '\\"')

        # --- 建立 GStreamer RTSP 接收管線 --- #
        # 接收 RTSP H.264 串流並解碼為 BGR
        # appsink 最多保留一個 Buffer, 避免累積過時影格
        pipeline = (
            f'rtspsrc location="{escaped}" protocols={protocol} '
            f"latency={latency} drop-on-latency=true ! "
            "application/x-rtp,media=video,encoding-name=H264 ! "
            "rtph264depay ! h264parse ! avdec_h264 ! "
            "videoconvert ! video/x-raw,format=BGR ! "
            "appsink max-buffers=1 drop=true "
            "sync=false enable-last-sample=false"
        )

        # --- 初始化影像接收器 --- #
        # 使用 GStreamer 接收影像, 由父類別管理背景執行緒與最新影格
        self._start(
            pipeline,
            timeout,
            retry,
            cv2.CAP_GSTREAMER,
        )


# ------------------------------------------------------------------------------------ #
# 接收 UDP 發送的 RTP/H.264 影像流 並解碼成 BGR
# ------------------------------------------------------------------------------------ #
class UDPFrameBuffer(_LatestFrameBuffer):
    """
    接收 UDP RTP/H.264 \\
    必須採用 GStreamer pipeline 方式接收, 無法支援 FFmpeg 方式接收

    args:
        • udp_host  - UDP Host
        • udp_port  - UDP Port
        • timeout   - 最長等待時間
        • retry     - 重起次數
    """
    def __init__(
        self, 
        udp_host: str = "127.0.0.1", 
        udp_port: int = 5600, 
        timeout: float = 5.0,
        retry: int = 1, backend: int | None = None
    ) -> None:

        # --- 檢查參數設定 --- #
        if not udp_host:
            raise ValueError("UDP host 不可為空字串")
        if not 1 <= udp_port <= 65535:
            raise ValueError("UDP port 必須介於 1 到 65535")

        # --- 建立 GStreamer pipeline 以接收 UDP RTP/H.264 並解碼成 BGR --- #
        self._camera_source = self._build_udp_gst_pipeline(udp_host, udp_port)
        if backend not in (None, cv2.CAP_ANY, cv2.CAP_GSTREAMER):
            raise ValueError("UDP pipeline 必須使用 CAP_GSTREAMER")

        # -- 開始接收影像流 --- #
        self._start(self._camera_source, timeout, retry, cv2.CAP_GSTREAMER)

    # ----------------- 建立 UDP -> GStreamer pipeline ----------------- #
    @staticmethod
    def _build_udp_gst_pipeline(udp_host: str, udp_port: int) -> str:
        return (
            f"udpsrc address={udp_host} port={udp_port} "
            "caps=application/x-rtp,media=video,encoding-name=H264,clock-rate=90000 ! "
            "rtph264depay ! h264parse ! avdec_h264 ! videoconvert ! "
            "video/x-raw,format=BGR ! "
            "appsink max-buffers=1 drop=true sync=false enable-last-sample=false"
        )


# ------------------------------------------------------------------------------------ #
# 接收 shmsink 發送的 BGR 影像
# ------------------------------------------------------------------------------------ #
class SHMFrameBuffer(_LatestFrameBuffer):
    """
    接收 shmsink 發送的 BGR 影像 \\
    GStreamer 影像流的格式必須是 BGR 且尺寸要與 發送端 相同

    args:
        • src       - 影像流地址
        • width     - 影像寬度
        • height    - 影像高度
        • timeout   - 最長等待時間
    """
    def __init__(
        self, 
        src: str, 
        width: int, 
        height: int, 
        timeout: float = 5.0
    ) -> None:
        
        if width <= 0 or height <= 0:
            raise ValueError("影像寬高必須為正數")
        
        escaped = src.replace("\\", "\\\\").replace('"', '\\"')
        pipeline = (
            f'shmsrc socket-path="{escaped}" is-live=true do-timestamp=true ! '
            f"video/x-raw,format=BGR,width={width},height={height},framerate=0/1 ! "
            "appsink max-buffers=1 drop=true sync=false enable-last-sample=false"
        )

        self._start(pipeline, timeout, 1, cv2.CAP_GSTREAMER, (width, height))


# ------------------------------------------------------------------------------------ #
# 讀取本機 Pi MIPI 相機, 輸出最新 BGR 影格
# ------------------------------------------------------------------------------------ #
class PiMIPIFrameBuffer(_LatestFrameBuffer):
    """
    接收 Pi MIPI 相機 -> 輸出 BGR (Picamera2 RGB888 的陣列排列)

    args:
        out_w           - 期望輸出寬度
        out_h           - 期望輸出高度
        timeout         - 啟動後等待第一張影格的秒數
        camera_num      - 相機編號，預設 0
        fps             - 可選的相機影格率
        camera_controls - 可選的 Picamera2 控制參數
    """

    def __init__(
        self,
        out_w: int = 1280,
        out_h: int = 720,
        timeout: float = 5.0,
        *,
        camera_num: int = 0,
        fps: float = 30,
        camera_controls: dict | None = None,
    ) -> None:

        # --- 檢查參數設定 --- #
        if (not isinstance(out_w, int) or not isinstance(out_h, int)
                or isinstance(out_w, bool) or isinstance(out_h, bool)
                or out_w <= 0 or out_h <= 0):
            raise ValueError("影像寬高必須為正整數")
        if not np.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout 必須為有限正數")

        if not isinstance(camera_num, int) or camera_num < 0:
            raise ValueError("camera_num 必須為非負整數")
        if fps is not None and (not np.isfinite(fps) or not 0 < fps <= 1_000_000):
            raise ValueError("fps 必須為 0 到 1000000 之間的有限正數")

        # --- 引入 Pi 相機模組 --- #
        from picamera2 import Picamera2
        from libcamera import controls

        # --------------------------------------------------------------
        # 初始化接收器狀態
        # stop          - 用於通知 reader 停止
        # queue         - 用於存放最新影格, 最大容量為 1
        # error         - 用於記錄 reader 執行緒的異常
        # size          - 用於記錄影格尺寸, 若指定 expected_size, 則檢查接收影格是否符合
        # picam2        - 存放 Picamera2 相機物件
        # release_lock  - 資源釋放互斥鎖，避免多個執行緒同時釋放資源
        # --------------------------------------------------------------
        self._stop = threading.Event()
        self._queue = Queue(maxsize=1)
        self._error = None
        self._size = (out_w, out_h)
        self._picam2 = None
        self._release_lock = threading.Lock()

        # --- 開啟 Pi MIPI 相機 --- #
        try:
            self._picam2 = Picamera2(camera_num)

            # --- 設定影像輸出格式 --- #
            config = self._picam2.create_video_configuration(
                main={"size": (out_w, out_h), "format": "RGB888"},
                queue=False,
            )
            self._picam2.configure(config)

            # --- 整合相機控制參數 --- #
            settings = {
                "AfMode": controls.AfModeEnum.Continuous,
                **(camera_controls or {}),
            }

            duration = round(1_000_000 / fps)
            settings["FrameDurationLimits"] = (duration, duration)

            # --- 檢查並套用相機支援的控制參數 --- #
            supported = self._picam2.camera_controls

            for name, value in settings.items():
                if name not in supported:
                    print(f"[WARNING] 相機不支援 {name}, 略過設定", flush=True)
                    continue

                try:
                    self._picam2.set_controls({name: value})
                except (ValueError, RuntimeError) as exc:
                    print(f"[WARNING] 無法設定 {name}: {exc}", flush=True)

            # --- 啟動相機並等待第一張影格 --- #
            self._picam2.post_callback = self._on_frame
            self._picam2.start()

            sample = self.read_with_timestamp(timeout)
            if sample is None:
                raise RuntimeError("Pi-MIPI 相機未在期限內收到第一幀")

            try:
                self._queue.put_nowait(sample)
            except Full:
                pass

        except BaseException:
            self.release()
            raise

    # ------------------------- 處理影像 & 紀錄影像格時間------------------------ #
    def _on_frame(self, request) -> None:
        if self._stop.is_set() or self._error is not None:
            return
        try:
            received_ns = time.time_ns()
            frame = request.make_array("main")
            width, height = self._size
            if frame.dtype != np.uint8 or frame.shape != (height, width, 3):
                raise RuntimeError(
                    f"Pi 影格格式不符: {frame.dtype}, {frame.shape}; "
                    f"預期 uint8, {(height, width, 3)}"
                )
            try:
                self._queue.get_nowait()
            except Empty:
                pass
            try:
                self._queue.put_nowait((frame, received_ns))
            except Full:
                pass
        except Exception as exc:
            self._error = exc

    # ---------------------------- 釋放影像資源 ---------------------------- #
    def release(self) -> None:
        with self._release_lock:
            self._stop.set()
            camera = self._picam2
            if camera is None:
                return
            try:
                camera.stop()
            finally:
                try:
                    camera.close()
                finally:
                    camera.post_callback = None
                    self._picam2 = None
                    while True:
                        try:
                            self._queue.get_nowait()
                        except Empty:
                            break
