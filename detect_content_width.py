#!/usr/bin/env python3
"""
detect_content_width.py — 检测视频实际内容宽度（排除黑边）
用法: python3 detect_content_width.py <video_file>
输出: 实际内容宽度（像素）
"""
import sys
import subprocess
import os
from PIL import Image
import numpy as np

def detect_content_width(video_path: str) -> int:
    """检测视频实际内容宽度，排除左右黑边"""
    probe = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'stream=width,height', '-of', 'csv=p=0', video_path],
        capture_output=True, text=True
    )
    parts = probe.stdout.strip().split(',')
    w, h = int(parts[0]), int(parts[1])

    # 已经是竖屏，直接返回宽度
    if h > w:
        return w

    # 横屏：检测左右黑边
    black_threshold = 30
    content_widths = []

    for t in [5, 15, 30]:
        tmp = f'/tmp/dcw_{t}.jpg'
        subprocess.run(
            ['ffmpeg', '-y', '-ss', str(t), '-i', video_path, '-vframes', '1', tmp],
            capture_output=True
        )
        if not os.path.exists(tmp):
            continue
        img = Image.open(tmp)
        arr = np.array(img)
        # 每列的平均亮度 (H, W, C) → (W,)
        col_brightness = arr.mean(axis=(0, 2))

        left_edge = 0
        for i in range(w):
            if col_brightness[i] > black_threshold:
                left_edge = i
                break
        right_edge = w
        for i in range(w - 1, -1, -1):
            if col_brightness[i] > black_threshold:
                right_edge = i + 1
                break

        content_widths.append(right_edge - left_edge)
        os.remove(tmp)

    if not content_widths:
        return w

    avg = int(sum(content_widths) / len(content_widths))
    # 如果内容宽度 < 原始宽度的 75%，认为有黑边
    if avg < w * 0.75:
        return avg
    return w


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python3 detect_content_width.py <video_file>", file=sys.stderr)
        sys.exit(1)
    width = detect_content_width(sys.argv[1])
    print(width)
