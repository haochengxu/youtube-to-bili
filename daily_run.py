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
    python3 daily_run.py --dry-run    # 只打印候选计划，不执行
    python3 daily_run.py --no-upload  # 同 --dry-run
    python3 daily_run.py --url "https://..." --title "..." # 单独上传
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from translator_cli import TranslatorError, run_llm

SCRIPT_DIR = Path(__file__).parent
HISTORY_FILE = SCRIPT_DIR / "uploaded" / "history.json"
SKIP_FILE = SCRIPT_DIR / "uploaded" / "skipped.json"  # 私有/不可用视频，跳过且不再重复探测

# 可选代理。需要时设置 YOUTUBE_PROXY=http://127.0.0.1:7890；默认直连，避免 cron 因本地代理未启动而失败。
PROXY = os.environ.get("YOUTUBE_PROXY", "").strip()

# yt-dlp 通用参数（保留 n challenge 修复）
YTDLP_COMMON_ARGS = [
    "--js-runtimes", "node",
    "--remote-components", "ejs:github",
]
_YTDLP_BASE: Optional[list[str]] = None

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


def load_skipped() -> set:
    if SKIP_FILE.exists():
        return {v["video_id"] for v in json.loads(SKIP_FILE.read_text())}
    return set()


def save_skipped(video_id: str, reason: str):
    SKIP_FILE.parent.mkdir(exist_ok=True)
    data = []
    if SKIP_FILE.exists():
        data = json.loads(SKIP_FILE.read_text())
    if any(v["video_id"] == video_id for v in data):
        return
    data.append({
        "video_id": video_id,
        "reason": reason,
        "skipped_at": datetime.now().isoformat(),
    })
    SKIP_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    log(f"⏭️  已记入跳过名单：{video_id}（{reason}）")


def detect_ytdlp_base() -> list[str]:
    """自动探测可用的 yt-dlp 命令。"""
    candidates: list[list[str]] = []
    env_cmd = os.environ.get("YTDLP_CMD", "").strip()
    if env_cmd:
        candidates.append(shlex.split(env_cmd))

    if shutil.which("yt-dlp"):
        candidates.append(["yt-dlp"])

    candidates.append([sys.executable, "-m", "yt_dlp"])

    seen: set[tuple[str, ...]] = set()
    for base_cmd in candidates:
        key = tuple(base_cmd)
        if not base_cmd or key in seen:
            continue
        seen.add(key)
        try:
            result = subprocess.run(
                base_cmd + ["--version"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return base_cmd + YTDLP_COMMON_ARGS

    raise RuntimeError(
        "找不到可用的 yt-dlp。请设置 YTDLP_CMD、确保 PATH 中有 yt-dlp，或安装当前 Python 环境的 yt_dlp 模块。"
    )


def get_ytdlp_base() -> list[str]:
    global _YTDLP_BASE
    if _YTDLP_BASE is None:
        _YTDLP_BASE = detect_ytdlp_base()
        log(f"使用 yt-dlp 命令：{' '.join(_YTDLP_BASE[:-len(YTDLP_COMMON_ARGS)] or _YTDLP_BASE)}")
    return _YTDLP_BASE


def ytdlp_cmd(*args: str) -> list[str]:
    return get_ytdlp_base() + list(args)


def ytdlp_network_args(url: str) -> list[str]:
    args = ["--no-warnings", "--cookies-from-browser", "chrome"]
    if PROXY:
        args.extend(["--proxy", PROXY])
    args.append(url)
    return args


def get_playlist_videos(url: str, max_items: int = 50) -> list:
    """从播放列表获取视频列表（倒序：最新在前）"""
    log(f"获取播放列表：{url}")
    cmd = ytdlp_cmd(
        "--flat-playlist",
        "--playlist-end", str(max_items),
        "--print", "%(id)s\t%(title)s\t%(duration)s",
        *ytdlp_network_args(url),
    )
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


# 永久不可用的标志（私有/删除/会员专属等）；命中才跳过，其余失败视为暂时性
_UNAVAILABLE_MARKERS = (
    "private", "unavailable", "removed", "deleted", "not available",
    "members-only", "members only", "terminated", "copyright",
)


def check_availability(url: str) -> tuple[bool, str]:
    """轻探视频是否可下载。返回 (是否可用, 原因)。
    只有命中"永久不可用"标志才判 False；网络抖动等其它失败一律按可用处理，
    交给 pipeline 去试/明天重试，避免误把好视频拉黑。"""
    r = subprocess.run(
        ytdlp_cmd("--simulate", "--no-warnings", "--quiet", *ytdlp_network_args(url)),
        capture_output=True, text=True, timeout=90,
    )
    if r.returncode == 0:
        return True, ""
    err = (r.stderr or "").strip()
    low = err.lower()
    if any(m in low for m in _UNAVAILABLE_MARKERS):
        last = err.splitlines()[-1] if err.splitlines() else err
        return False, last[:160]
    return True, ""  # 非"不可用"类失败 → 当作可用，让后续流程去处理/重试


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
        ytdlp_cmd("--get-id", *ytdlp_network_args(url)),
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
        ytdlp_cmd("--get-description", *ytdlp_network_args(url)),
        capture_output=True, text=True, timeout=120
    )
    if r.returncode == 0 and r.stdout.strip():
        desc = r.stdout.strip()
        # 取第一段（第一个空行前）
        first_para = desc.split("\n\n")[0].strip()
        if len(first_para) > 400:
            first_para = first_para[:400]
        # 翻译成中文
        prompt = f"把下面的英文视频简介翻译成中文，自然流畅，不超过150字，只输出中文：\n{first_para}"
        try:
            translated = run_llm(prompt, timeout=60)
            if translated:
                return translated
        except TranslatorError as exc:
            log(f"[WARN] 简介翻译失败: {exc}")
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
    """用配置的翻译后端翻译视频标题"""
    prompt = (
        f"把下面的英文视频标题翻译成中文，要简洁，保留核心含义，不超过20字，只输出中文标题：\n{en_title}"
    )
    try:
        translated = run_llm(prompt, timeout=60)
        if translated:
            return translated
    except TranslatorError as exc:
        log(f"[WARN] 标题翻译失败: {exc}")
    return en_title  # fallback


def get_video_id(url: str) -> str:
    result = subprocess.run(
        ytdlp_cmd("--get-id", *ytdlp_network_args(url)),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip()


def get_video_title(url: str) -> str:
    result = subprocess.run(
        ytdlp_cmd("--get-title", *ytdlp_network_args(url)),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip()


def log_plan(label: str, url: str, title: str):
    log(f"[PLAN] {label}: {title}")
    log(f"[PLAN] URL: {url}")


def process_one(url: str, speaker_zh: str, speaker_en: str, en_title: str, done: set) -> bool:
    """完整跑一个视频。返回是否成功。"""
    zh_title = translate_title(en_title)
    bili_title = make_title(speaker_zh, speaker_en, en_title, zh_title)
    log(f"标题：{bili_title}")

    out_file = run_pipeline(url)
    if not out_file:
        return False

    # 获取 video_id
    video_id = get_video_id(url)

    bvid = upload_to_bili(out_file, bili_title, video_id, source_url=url)
    if bvid:
        save_history(video_id, bvid, bili_title)
        return True
    return False


def run_branch(label, videos, done, skipped, speaker_zh, speaker_en,
               plan_only=False, min_dur=0, max_dur=float("inf"),
               max_unavailable=8):
    """挑下一个未处理视频处理；遇私有/不可用则跳过并记账，自动顺延下一个。
    暂时性失败（网络/压制等）则停止，留待明天重试同一视频，不拉黑。"""
    excluded = done | skipped
    pool = [
        v for v in videos
        if v["id"] not in excluded
        and (not v["duration"] or min_dur <= v["duration"] <= max_dur)
    ]
    skipped_this_run = 0
    for v in pool:
        url = f"https://www.youtube.com/watch?v={v['id']}"
        ok, reason = check_availability(url)
        if not ok:
            log(f"{label}：候选不可用，跳过 → {v['title'][:40]}（{reason}）")
            save_skipped(v["id"], reason)
            skipped.add(v["id"])
            skipped_this_run += 1
            if skipped_this_run >= max_unavailable:
                log(f"{label}：连续 {max_unavailable} 个不可用，今日停止")
                return
            continue
        if plan_only:
            log_plan(f"{label}候选", url, v["title"])
            return
        if process_one(url, speaker_zh, speaker_en, v["title"], done):
            done.add(v["id"])
        else:
            log(f"{label}：处理失败（疑似暂时性），保留该视频明天重试")
        return  # 处理过一个（成功或暂时失败）即结束本支线
    log(f"⚠️  {label}：没找到可处理的新视频")


def preflight(check_translator: bool):
    """启动前自检：代理可达 + 翻译后端鉴权。
    任一失败立即退出，避免跑到一半（下载+Whisper 都做完）才在翻译步死掉。"""
    # 1. 代理探活（仅当配置了 YOUTUBE_PROXY）
    if PROXY:
        log(f"自检：代理 {PROXY} → YouTube ...")
        r = subprocess.run(
            ["curl", "-sI", "--max-time", "10", "-x", PROXY, "https://www.youtube.com"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            log(f"[FATAL] 代理不可用（YouTube 连不上）。Clash 没开？curl exit={r.returncode}")
            sys.exit(2)
        log("自检：代理 OK")

    # 2. 翻译后端鉴权探活（claude 后端最容易因长效 token 过期而 401）
    backend = (os.environ.get("TRANSLATOR") or "").strip().lower()
    if check_translator and backend == "claude":
        log("自检：claude 翻译后端鉴权 ...")
        try:
            out = run_llm("只回复两个字：OK", timeout=60)
        except TranslatorError as exc:
            log(f"[FATAL] claude 后端鉴权/调用失败：{exc}")
            log("        多半是长效 token 过期，重跑 `claude setup-token` 并更新密钥文件后再试。")
            sys.exit(3)
        log(f"自检：claude OK（返回 {out[:20]!r}）")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--long-only", action="store_true")
    parser.add_argument("--short-only", action="store_true")
    parser.add_argument("--url", help="直接指定 YouTube URL（单独上传）")
    parser.add_argument("--title", help="配合 --url 使用的 B 站标题（可选）")
    parser.add_argument("--dry-run", action="store_true", help="只获取候选视频并打印计划，不运行 pipeline / upload / history")
    parser.add_argument("--no-upload", action="store_true", help="同 --dry-run，只打印计划")
    args = parser.parse_args()
    plan_only = args.dry_run or args.no_upload

    preflight(check_translator=not plan_only)

    done = load_history()
    log(f"已处理视频数：{len(done)}")
    if plan_only:
        log("计划模式：只打印候选视频，不运行 pipeline、不上传、不写 history")

    # 单独上传模式
    if args.url:
        url = args.url
        if args.title:
            bili_title = args.title
        else:
            # 自动获取标题并翻译
            en_title = get_video_title(url)
            if plan_only:
                bili_title = en_title
            else:
                zh_title = translate_title(en_title)
                bili_title = f"{zh_title} {en_title}"
        log(f"单独上传模式：{url}")
        log(f"标题：{bili_title}")
        if plan_only:
            log_plan("单独上传", url, bili_title)
            return
        out_file = run_pipeline(url)
        if out_file:
            video_id = get_video_id(url)
            bvid = upload_to_bili(out_file, bili_title, video_id, source_url=url)
            if bvid:
                save_history(video_id, bvid, bili_title)
                log(f"✅ 完成：{bvid}")
        return

    skipped = load_skipped()
    if skipped:
        log(f"跳过名单（私有/不可用）：{len(skipped)} 个")

    # 长视频
    if not args.short_only:
        log("=== 长视频（Michael Singer）===")
        videos = get_playlist_videos(LONG_PLAYLIST, max_items=30)
        run_branch("长视频", videos, done, skipped,
                   LONG_SPEAKER_ZH, LONG_SPEAKER_EN,
                   plan_only=plan_only, min_dur=LONG_MIN_DURATION)

    # 短视频
    if not args.long_only:
        log("=== 短视频（Adyashanti）===")
        videos = get_playlist_videos(SHORT_CHANNEL, max_items=20)
        run_branch("短视频", videos, done, skipped,
                   SHORT_SPEAKER_ZH, SHORT_SPEAKER_EN,
                   plan_only=plan_only, max_dur=SHORT_MAX_DURATION)

    log("=== daily_run.py 完成 ===")


if __name__ == "__main__":
    main()
