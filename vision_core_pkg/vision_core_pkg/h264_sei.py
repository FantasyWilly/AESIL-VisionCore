#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
File    : h264_sei.py
Author  : FantasyWilly
Email   : bc697522h04@gmail.com
SPDX-License-Identifier: Apache-2.0

功能總覽:
    • 定義自訂 SEI UUID 與 H.264 NAL 起始碼
    • 解析 H.264 Annex B 位元流中的 NAL Units
    • 處理 RBSP 與 EBSP 格式轉換
    • 建立包含影格序號與接收時間的 SEI
    • 解析 SEI 中的影格時間戳記
    • 將自訂 SEI 插入 H.264 影格

遵循:
    • Google Python Style Guide (含區段標題)
    • PEP 8 (行寬 ≤ 88, snake_case, 2 空行區段分隔)
"""

# ------------------------------------------------------------------------------------ #
# Import
# ------------------------------------------------------------------------------------ #
# 標準庫
import re
import struct
import uuid


# ------------------------------------------------------------------------------------ #
# 全域參數
# ------------------------------------------------------------------------------------ #
# 自訂 SEI 識別碼, 用於辨識本系統所寫入的時間戳記資訊 (16 Bytes)
UUID = uuid.UUID("c852787a-d31a-4a4a-8275-8de2726d741a").bytes

# H.264 Annex B NAL Unit 起始碼 (4 Bytes)
START = b"\x00\x00\x00\x01"


# ------------------------------------------------------------------------------------ #
# 解析 H.264 NAL Units
# ------------------------------------------------------------------------------------ #
def nals(data):
    """
    解析 H.264 Annex B 位元流中的各個 NAL Unit

    args:
        data: H.264 編碼後的位元流

    yields:
        NAL Unit 起始碼位置與不含起始碼的 NAL 資料
    """

    # --- 搜尋所有 3 Bytes / 4 Bytes 的 NAL 起始碼 --- #
    markers = list(
        re.finditer(b"\x00\x00\x00\x01|\x00\x00\x01", data)
    )

    # --- 依照起始碼位置切割各個 NAL Unit --- #
    for index, marker in enumerate(markers):
        end = (
            markers[index + 1].start()
            if index + 1 < len(markers)
            else len(data)
        )

        yield marker.start(), data[marker.end():end]


# ------------------------------------------------------------------------------------ #
# RBSP -> EBSP: 插入 Emulation Prevention Byte
# ------------------------------------------------------------------------------------ #
def escape(rbsp):
    """
    將 RBSP 轉換成 EBSP

    插入 0x03 防止 NAL 內容中的特殊位元組序列, 
    被 H.264 解碼器誤判為 NAL 起始碼

    args:
        rbsp: 尚未進行防競爭處理的原始位元組序列

    returns:
        bytes: 插入防競爭位元組後的 EBSP 資料
    """

    # --- 初始化輸出緩衝區與連續零計數 --- #
    output = bytearray()
    zeros = 0

    # --- 掃描 RBSP 並插入防競爭位元組 --- #
    for value in rbsp:
        if zeros >= 2 and value <= 3:
            output.append(3)
            zeros = 0

        output.append(value)
        zeros = zeros + 1 if value == 0 else 0

    return bytes(output)


# ------------------------------------------------------------------------------------ #
# EBSP -> RBSP: 移除 Emulation Prevention Byte
# ------------------------------------------------------------------------------------ #
def unescape(ebsp):
    """
    將 EBSP 還原成 RBSP

    移除編碼時插入的 0x03, 還原原始 SEI 資料

    args:
        ebsp: 已進行防競爭處理的位元組序列

    returns:
        bytes: 移除防競爭位元組後的 RBSP 資料
    """

    # --- 初始化輸出緩衝區與連續零計數 --- #
    output = bytearray()
    zeros = 0

    # --- 掃描 EBSP 並移除防競爭位元組 --- #
    for value in ebsp:
        if zeros >= 2 and value == 3:
            zeros = 0
            continue

        output.append(value)
        zeros = zeros + 1 if value == 0 else 0

    return bytes(output)


# ------------------------------------------------------------------------------------ #
# 建立自訂 SEI NAL Unit
# ------------------------------------------------------------------------------------ #
def make_sei(frame_id, received_ns):
    """
    建立包含影格序號與接收時間的 H.264 SEI

    args:
        frame_id: 影格序號
        received_ns: 影格接收時的 Unix 奈秒時間戳記

    returns:
        完整的 H.264 SEI NAL Uni, 包含 Annex B 起始碼
    """

    # --- 封裝自訂 SEI Payload --- #
    # UUID        : 16 Bytes, 自訂資料識別碼
    # Version     :  1 Byte, 資料格式版本
    # Frame ID    :  8 Bytes, 影格序號
    # Received NS :  8 Bytes, Unix 奈秒時間戳記
    #
    # >BQQ 代表 Big Endian, uint8, uint64, uint64
    payload = UUID + struct.pack(">BQQ", 1, frame_id, received_ns)

    # --- 建立 SEI RBSP --- #
    # 5    : SEI Payload Type (user_data_unregistered)
    # len  : SEI Payload Size
    # 0x80 : RBSP Trailing Bits
    rbsp = bytes([5, len(payload)]) + payload + b"\x80"

    # --- 建立完整 SEI NAL Unit --- #
    # START : Annex B 起始碼
    # 0x06  : SEI NAL Header (NAL Unit Type = 6)
    # EBSP  : 經過防競爭處理的 SEI 資料
    return START + b"\x06" + escape(rbsp)


# ------------------------------------------------------------------------------------ #
# 解析 H.264 SEI 時間戳記
# ------------------------------------------------------------------------------------ #
def read_timestamps(data):
    """
    從 H.264 位元流中讀取本系統寫入的 SEI 時間戳記

    args:
        data: H.264 Annex B 位元流

    returns:
        包含 (frame_id, received_ns) 的列表
    """

    # --- 初始化時間戳記結果列表 --- #
    result = []

    # --- 搜尋所有 SEI NAL Units --- #
    for _, nal in nals(data):
        if not nal or nal[0] & 31 != 6:
            continue

        # --- 移除 NAL Header 並還原 RBSP --- #
        rbsp = unescape(nal[1:])
        offset = 0

        # --- 逐一解析 SEI Messages --- #
        while offset < len(rbsp) and rbsp[offset:] != b"\x80":
            fields = []
            for _ in range(2):
                value = 0
                while offset < len(rbsp) and rbsp[offset] == 255:
                    value += 255
                    offset += 1

                if offset >= len(rbsp):
                    raise ValueError("SEI header truncated")

                value += rbsp[offset]
                offset += 1
                fields.append(value)

            kind, size = fields

            # --- 提取 SEI Payload 並檢查資料完整性 --- #
            payload = rbsp[offset:offset + size]

            if len(payload) != size:
                raise ValueError("SEI payload truncated")

            offset += size

            # --- 確認 SEI 類型與自訂 UUID --- #
            if kind == 5 and payload[:16] == UUID:
                version, frame_id, received_ns = struct.unpack(
                    ">BQQ", payload[16:]
                )

                if version != 1:
                    raise ValueError("Unknown timestamp version")

                result.append((frame_id, received_ns))

    return result


# ------------------------------------------------------------------------------------ #
# 將時間戳記 SEI 插入 H.264 影格
# ------------------------------------------------------------------------------------ #
def insert_timestamp(
    data: bytes,
    frame_id: int,
    received_ns: int,
) -> bytes:
    """
    將自訂 SEI 插入 H.264 位元流的第一個 VCL NAL 之前

    args:
        data: H.264 Annex B 編碼影格
        frame_id: 影格序號
        received_ns: 影格接收時的 Unix 奈秒時間戳記

    returns:
        包含自訂時間戳記 SEI 的 H.264 位元流
    """

    # --- 尋找第一個 VCL NAL Unit 的起始位置 --- #
    # NAL Unit Type 1 ~ 5 為此處辨識的 VCL 影像資料類型
    position = next(
        (
            offset
            for offset, nal in nals(data)
            if nal and 1 <= (nal[0] & 31) <= 5
        ),
        None,
    )

    # --- 檢查是否存在 VCL 影像資料 --- #
    if position is None:
        raise ValueError("編碼輸出未包含完整影格的 VCL NAL")

    # --- 建立 SEI 並插入第一個 VCL NAL 之前 --- #
    return (
        data[:position]
        + make_sei(frame_id, received_ns)
        + data[position:]
    )
