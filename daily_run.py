#!/usr/bin/env python3
"""
daily_run.py — 每日自动流水线

逻辑：
1. 读取 uploaded/history.json，获取已处理的 video_id 集合
2. 从播放列表倒序（最新→最旧）找第一个未处理视频
3. 调用 pipeline.sh 处理
4. 调用 bili_upload_v2.py 上传
5. 写入 history.json

用法：
    python3 daily_run.py              # 跑一长一短
    python3 daily_run.py --long-only  # 只跑长视频
    python3 daily_run.py --short-only # 只跑短视频
    python3 daily_run.py --url "https://..." --title "..." # 单独上传
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).parent
HISTORY_FILE = SCRIPT_DIR / "uploaded" / "history.json"

# 代理
PROXY = "http://127.0.0.1:7890"

# yt-dlp 基础命令（python3.11 + n challenge 修复）
YTDLP_BASE = [
    "python3.11", "-m", "yt_dlp",
    "--js-runtimes", "node",
    "--remote-components", "ejs:github",
]

# 长视频：Michael Singer 播放列表
LONG_PLAYLIST = "https://www.youtube.com/playlist?list=PLyOuAoSmZkKoESr2acNWwhznusbBkKXsT"
LONG_SPEAKER_ZH = "迈克尔·辛格"
LONG_SPEAKER_EN = "Michael Singer"
LONG_MIN_DURATION = 600  # 10分钟以上算长视频

# 短视频：Adyashanti（取最新 Shorts，≤3分钟）
SHORT_CHANNEL = "https://www.youtube.com/@Adyashanti/shorts"
SHORT_SPEAKER_ZH = "阿迪亚香提"
SHORT_SPEAKER_EN = "Adyashanti"
SHORT_MAX_DURATION = 180  # 3分钟以下


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_history() -> set:
    if HISTORY_FILE.exists():
        data = json.loads(HISTORY_FILE.read_text())
        return {v["video_id"] for v in data}
    return set()


def save_history(video_id: str, bvid: str, title: str):
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    data = []
    if HISTORY_FILE.exists():
        data = json.loads(HISTORY_FILE.read_text())
    data.append({
        "video_id": video_id,
        "bvid": bvid,
        "title": title,
        "uploaded_at": datetime.now().isoformat(),
    })
    HISTORY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    log(f"✅ history.json 已更新：{video_id} → {bvid}")


def get_playlist_videos(url: str, max_items: int = 50) -> list:
    """从播放列表获取视频列表（倒序：最新在前）"""
    log(f"获取播放列表：{url}")
    cmd = YTDLP_BASE + [
        "--flat-playlist",
        "--playlist-end", str(max_items),
        "--print", "%(id)s\t%(title)s\t%(duration)s",
        "--no-warnings",
        "--cookies-from-browser", "chrome",
        "--proxy", PROXY,
        url,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        log(f"[WARN] yt-dlp playlist error: {r.stderr[:200]}")
        return []

    videos = []
    for line in r.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            vid_id = parts[0].strip()
            title = parts[1].strip()
            try:
                duration = float(parts[2]) if len(parts) >= 3 and parts[2].strip() not in ("", "NA", "None") else 0
            except ValueError:
                duration = 0
            videos.append({"id": vid_id, "title": title, "duration": duration})
    log(f"  获取到 {len(videos)} 个视频")
    return videos  # yt-dlp 默认顺序 = 列表顺序；播放列表通常新→旧


def pick_next(videos: list, done: set,
              min_dur: float = 0, max_dur: float = float("inf")) -> Optional[dict]:
    for v in videos:
        if v["id"] in done:
            continue
        if v["duration"] and not (min_dur <= v["duration"] <= max_dur):
            continue
        return v
    return None


def run_pipeline(url: str) -> Optional[str]:
    """运行 pipeline.sh，返回输出视频路径（output/<video_id>.mp4）"""
    log(f"▶️  运行 pipeline.sh: {url}")
    r = subprocess.run(
        ["bash", str(SCRIPT_DIR / "pipeline.sh"), url],
        cwd=SCRIPT_DIR,
        timeout=7200,  # 2小时上限
    )
    if r.returncode != 0:
        log(f"[ERROR] pipeline.sh 失败，exit={r.returncode}")
        return None

    # 找生成的 mp4
    video_id_cmd = subprocess.run(
        YTDLP_BASE + ["--get-id", "--no-warnings", "--cookies-from-browser", "chrome", "--proxy", PROXY, url],
        capture_output=True, text=True, timeout=30
    )
    video_id = video_id_cmd.stdout.strip()
    out_file = SCRIPT_DIR / "output" / f"{video_id}.mp4"
    if out_file.exists():
        return str(out_file)
    log(f"[ERROR] 找不到输出文件：{out_file}")
    return None


def get_video_desc(url: str) -> str:
    """抓 YouTube 视频简介，翻译成中文（前200字）"""
    r = subprocess.run(
        YTDLP_BASE + ["--get-description", "--no-warnings", "--cookies-from-browser", "chrome", "--proxy", PROXY, url],
        capture_output=True, text=True, timeout=30
    )
    if r.returncode == 0 and r.stdout.strip():
        desc = r.stdout.strip()
        # 取第一段（第一个空行前）
        first_para = desc.split("\n\n")[0].strip()
        if len(first_para) > 400:
            first_para = first_para[:400]
        # 翻译成中文
        prompt = f"把下面的英文视频简介翻译成中文，自然流畅，不超过150字，只输出中文：\n{first_para}"
        t = subprocess.run(
            ["hermes", "chat", "-q", prompt, "-Q"],
            capture_output=True, text=True, timeout=60
        )
        if t.returncode == 0 and t.stdout.strip():
            return t.stdout.strip()
        return desc  # 翻译失败就用原文
    return ""


def upload_to_bili(video_file: str, title: str, video_id: str, source_url: str = "") -> Optional[str]:
    """上传到 B 站，返回 bvid"""
    log(f"📤 上传：{title}")
    desc = get_video_desc(source_url) if source_url else ""
    r = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "bili_upload_v2.py"),
            video_file,
            "--title", title,
            "--desc", desc,
            "--source", source_url,
        ],
        cwd=SCRIPT_DIR,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if r.returncode != 0:
        log(f"[ERROR] 上传失败：{r.stderr[:300]}")
        return None

    # 从输出里提取 bvid
    for line in (r.stdout + r.stderr).splitlines():
        if "'bvid'" in line:
            import re
            m = re.search(r"'bvid': '(BV\w+)'", line)
            if m:
                return m.group(1)
        if "BV" in line:
            import re
            m = re.search(r"BV\w+", line)
            if m:
                return m.group(0)
    return "BV_UNKNOWN"


def clean_youtube_title(title: str, speaker_en: str) -> str:
    """清理 YouTube 标题：去 hashtag、频道名后缀、重复的演讲者名"""
    import re
    # 去掉 hashtag
    title = re.sub(r'\s*#\S+', '', title).strip()
    # 去掉常见的 "| xxx Podcast", "| xxx Channel" 等后缀
    title = re.sub(r'\s*\|[^|]*$', '', title).strip()
    # 如果标题里已经包含演讲者名，去掉
    if speaker_en.lower() in title.lower():
        # 去掉 "Speaker Name - " 或 "Speaker Name: " 前缀
        title = re.sub(rf'^{re.escape(speaker_en)}\s*[-:–—]\s*', '', title, flags=re.IGNORECASE).strip()
    return title


def make_title(speaker_zh: str, speaker_en: str, en_title: str, zh_title: str) -> str:
    """格式：迈克尔·辛格 Michael Singer｜中文标题 English Title"""
    en_title = clean_youtube_title(en_title, speaker_en)
    return f"{speaker_zh} {speaker_en}｜{zh_title} {en_title}"


def translate_title(en_title: str) -> str:
    """用 hermes 翻译视频标题"""
    prompt = (
        f"把下面的英文视频标题翻译成中文，要简洁，保留核心含义，不超过20字，只输出中文标题：\n{en_title}"
    )
    r = subprocess.run(
        ["hermes", "chat", "-q", prompt, "-Q"],
        capture_output=True, text=True, timeout=60
    )
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    return en_title  # fallback


def process_one(url: str, speaker_zh: str, speaker_en: str, en_title: str, done: set) -> bool:
    """完整跑一个视频。返回是否成功。"""
    zh_title = translate_title(en_title)
    bili_title = make_title(speaker_zh, speaker_en, en_title, zh_title)
    log(f"标题：{bili_title}")

    out_file = run_pipeline(url)
    if not out_file:
        return False

    # 获取 video_id
    video_id_cmd = subprocess.run(
        YTDLP_BASE + ["--get-id", "--no-warnings", "--cookies-from-browser", "chrome", "--proxy", PROXY, url],
        capture_output=True, text=True, timeout=30
    )
    video_id = video_id_cmd.stdout.strip()

    bvid = upload_to_bili(out_file, bili_title, video_id, source_url=url)
    if bvid:
        save_history(video_id, bvid, bili_title)
        return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--long-only", action="store_true")
    parser.add_argument("--short-only", action="store_true")
    parser.add_argument("--url", help="直接指定 YouTube URL（单独上传）")
    parser.add_argument("--title", help="配合 --url 使用的 B 站标题（可选）")
    args = parser.parse_args()

    done = load_history()
    log(f"已处理视频数：{len(done)}")

    # 单独上传模式
    if args.url:
        url = args.url
        if args.title:
            bili_title = args.title
            en_title = args.title
            zh_title = args.title
        else:
            # 自动获取标题并翻译
            r = subprocess.run(
                YTDLP_BASE + ["--get-title", "--no-warnings", "--cookies-from-browser", "chrome", "--proxy", PROXY, url],
                capture_output=True, text=True, timeout=30
            )
            en_title = r.stdout.strip()
            zh_title = translate_title(en_title)
            bili_title = f"{zh_title} {en_title}"
        log(f"单独上传模式：{url}")
        log(f"标题：{bili_title}")
        out_file = run_pipeline(url)
        if out_file:
            video_id_cmd = subprocess.run(
                YTDLP_BASE + ["--get-id", "--no-warnings", "--cookies-from-browser", "chrome", "--proxy", PROXY, url],
                capture_output=True, text=True, timeout=30
            )
            video_id = video_id_cmd.stdout.strip()
            bvid = upload_to_bili(out_file, bili_title, video_id, source_url=url)
            if bvid:
                save_history(video_id, bvid, bili_title)
                log(f"✅ 完成：{bvid}")
        return

    # 长视频
    if not args.short_only:
        log("=== 长视频（Michael Singer）===")
        videos = get_playlist_videos(LONG_PLAYLIST, max_items=30)
        v = pick_next(videos, done, min_dur=LONG_MIN_DURATION)
        if v:
            url = f"https://www.youtube.com/watch?v={v['id']}"
            process_one(url, LONG_SPEAKER_ZH, LONG_SPEAKER_EN, v["title"], done)
        else:
            log("⚠️  长视频：没找到未处理的视频")

    # 短视频
    if not args.long_only:
        log("=== 短视频（Adyashanti）===")
        videos = get_playlist_videos(SHORT_CHANNEL, max_items=20)
        v = pick_next(videos, done, max_dur=SHORT_MAX_DURATION)
        if v:
            url = f"https://www.youtube.com/watch?v={v['id']}"
            process_one(url, SHORT_SPEAKER_ZH, SHORT_SPEAKER_EN, v["title"], done)
        else:
            log("⚠️  短视频：没找到未处理的视频")

    log("=== daily_run.py 完成 ===")


if __name__ == "__main__":
    main()
