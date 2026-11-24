# <div align="center">AESIL - VisonCore</div>

## <div align="center">Outline</div>

- [依賴項 (Dependencies)](#dependencies)
- [程式下載 (Downloads)](#downloads)
- [影像串流伺服器 (Stream Service)](#stream-service)
- [影像串流 (Live Stream)](#live-stream)
- [影像分流 (Tee)](#tee)

## <div align="center">Dependencies</div>

> ★ 需要安裝 (Required)

```bash
# 更新安裝清單
sudo apt update
```

```bash
# 安裝 GStreamer 套件
sudo apt install -y \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav \
    gstreamer1.0-rtsp \
    python3-gi \
    python3-gst-1.0 \
    gir1.2-gstreamer-1.0 \
    gir1.2-gst-plugins-base-1.0
```
> ★ 選擇性安裝 (Option)

```bash
# 安裝 Pi Camera Lib 庫 (有 Raspberry Pi 才須安裝)
sudo apt install -y \
    python3-picamera2 \
    python3-libcamera
```

---

## <div align="center">Downloads</div>

*Step1* - 下載至 ROS2 的工作空間
```bash
cd ~/<your_workspace>/src
git clone https://github.com/FantasyWilly/AESIL-VisionCore.git
```
---

*Step2* - 編譯工作空間
```bash
cd ~/<your_workspace>
colcon build
source ~/.bashrc
```
---

## <div align="center">Stream-Service</div>

  ### [ 影像串流 ] - Mediamtx

  `官網連結:` [ Mediamtx 官方 Github  ](https://github.com/bluenviron/mediamtx)  
  `下載連結:` [ Mediamtx 官方 Release ](https://github.com/bluenviron/mediamtx/releases)

  - Linux

    ```bash
    cd <your_mediamtx_dir>
    ./mediamtx
    ```

  - Windows

    ```bash
    直接點 .exe 執行檔即可
    ```

    ---

## <div align="center">Live-Stream</div>

  ### 影像串流 ( 接收影像 -> MediaMTX )

  - 查看使用說明

    ```bash
    ros2 run vision_pkg main_streaming -h
    ros2 run vision_pkg main_streaming --rtsp -h
    ```

  - 開啟程式

    ```bash
    ros2 run vision_pkg main_streaming          # 預設 V4L2
    ros2 run vision_pkg main_streaming --rtsp   # 指定其他影像來源
    ```
  ---

## <div align="center">Tee</div>

  ### 影像分流 ( 接收影像 -> SHM )

  - 查看使用說明

    ```bash
    ros2 run vision_pkg main_tee -h
    ros2 run vision_pkg main_tee --rtsp -h
    ```

  - 開啟程式

    ```bash
    ros2 run vision_pkg main_tee                # 預設 V4L2 
    ros2 run vision_pkg main_tee --rtsp         # 指定其他影像來源
    ```
  ---