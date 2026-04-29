#!/usr/bin/env python3
"""
每日自动处理脚本：从队列取一个视频 → 下载 → 翻译 → 压制 → 上传 B站

用法: python3 daily_process.py [--dry-run]
"""
import json
import os
import sys
import subprocess
import time
from pathlib import Path
from datetime import datetime

BASE_DIR = Path.home() / "youtube-to-bili"
QUEUE_FILE = BASE_DIR / "queue.json"
COOKIES_FILE = BASE_DIR / "cookies.json"
BILIUP_PATH = Path.home() / "Library/Python/3.9/bin/biliup"

# B站分区 ID
TID_HUMANITY = 21    # 人文·历史 → 野生技术协会 → 不太合适
TID_LIFE = 138       # 生活 → 其他
TID_KNOWLEDGE = 231  # 知识 → 社科·法律·心理


def load_queue():
    with open(QUEUE_FILE) as f:
        return json.load(f)

def save_queue(queue):
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)

def mark_video(queue, video_id, status, bvid=None, error=None):
    for v in queue["videos"]:
        if v["video_id"] == video_id:
            v["status"] = status
            if status == "done":
                v["processed_at"] = datetime.now().isoformat()
            if bvid:
                v["bili_bvid"] = bvid
            if error:
                v["error"] = str(error)
            break
    save_queue(queue)

def get_next_pending(queue):
    for v in queue["videos"]:
        if v["status"] == "pending":
            return v
    return None

def run_pipeline(video):
    """Run the full pipeline: download → merge subtitles → translate → make ASS → encode."""
    vid = video["video_id"]
    url = video["source_url"]
    
    print(f"\n{'='*60}")
    print(f"🎬 处理视频: {video['title']}")
    print(f"   ID: {vid}")
    print(f"   URL: {url}")
    print(f"{'='*60}\n")
    
    # Run pipeline.sh
    result = subprocess.run(
        ["bash", str(BASE_DIR / "pipeline.sh"), url],
        cwd=str(BASE_DIR),
        capture_output=True, text=True, timeout=1800  # 30 min max
    )
    
    print("STDOUT:", result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[-1000:] if len(result.stderr) > 1000 else result.stderr)
    
    if result.returncode != 0:
        raise RuntimeError(f"Pipeline failed with exit code {result.returncode}")
    
    # Find output file
    output_candidates = [
        BASE_DIR / f"output/{vid}_v2.mp4",
        BASE_DIR / f"output/{vid}.mp4",
    ]
    for output_file in output_candidates:
        if output_file.exists():
            return str(output_file)
    
    raise RuntimeError(f"Output file not found. Expected: {output_candidates}")

def upload_to_bilibili(video, output_file):
    """Upload to Bilibili using bilibili-api-python."""
    import asyncio
    
    # Generate cover from video
    cover_file = output_file.replace(".mp4", "_cover.jpg")
    subprocess.run(
        ["ffmpeg", "-y", "-i", output_file, "-ss", "5", "-frames:v", "1", "-update", "1", cover_file],
        capture_output=True, timeout=60
    )
    
    # Build title: keep original English title, prepend 【中英双语】
    original_title = video["title"]
    # Remove " | Michael Singer Podcast" suffix if present
    clean_title = original_title.split(" | ")[0] if " | " in original_title else original_title
    bili_title = f"【中英双语】{clean_title}"
    # B站标题限制80字
    if len(bili_title) > 80:
        bili_title = bili_title[:77] + "..."
    
    source_url = video["source_url"]
    desc = f"搬运自 YouTube Sounds True 频道 Michael Singer Podcast\n原链接：{source_url}"
    tags = "灵性成长,冥想,Michael Singer,心灵,英语学习"
    
    # Use bili_upload_v2.py
    result = subprocess.run(
        [sys.executable, str(BASE_DIR / "bili_upload_v2.py"),
         output_file,
         "--title", bili_title,
         "--desc", desc,
         "--tag", tags,
         "--source", source_url,
         "--tid", str(TID_KNOWLEDGE),
         "--cover", cover_file if os.path.exists(cover_file) else "",
        ],
        cwd=str(BASE_DIR),
        capture_output=True, text=True, timeout=600
    )
    
    print("Upload output:", result.stdout)
    if result.stderr:
        print("Upload stderr:", result.stderr[-500:])
    
    if result.returncode != 0:
        raise RuntimeError(f"Upload failed: {result.stdout}\n{result.stderr}")
    
    # Extract BV号 from output
    bvid = None
    for line in result.stdout.split("\n"):
        if "bvid" in line.lower() or "BV" in line:
            import re
            match = re.search(r"BV[a-zA-Z0-9]+", line)
            if match:
                bvid = match.group()
                break
    
    return bvid

def main():
    dry_run = "--dry-run" in sys.argv
    
    queue = load_queue()
    video = get_next_pending(queue)
    
    if not video:
        print("✅ 队列中没有待处理的视频")
        return
    
    vid = video["video_id"]
    
    if dry_run:
        print(f"[DRY RUN] 将要处理: {video['title']} ({vid})")
        return
    
    try:
        # Step 1: Download + translate + encode
        mark_video(queue, vid, "downloading")
        output_file = run_pipeline(video)
        print(f"\n✅ Pipeline 完成: {output_file}")
        
        # Step 2: Upload
        mark_video(queue, vid, "uploading")
        bvid = upload_to_bilibili(video, output_file)
        
        # Step 3: Mark done
        mark_video(queue, vid, "done", bvid=bvid)
        print(f"\n🎉 上传成功！ BV号: {bvid}")
        print(f"   链接: https://www.bilibili.com/video/{bvid}")
        
        # Summary
        queue = load_queue()
        pending = sum(1 for v in queue["videos"] if v["status"] == "pending")
        done = sum(1 for v in queue["videos"] if v["status"] == "done")
        print(f"\n📊 队列: {done} 已完成, {pending} 待处理")
        
    except Exception as e:
        print(f"\n❌ 处理失败: {e}")
        mark_video(queue, vid, "failed", error=str(e))
        raise

if __name__ == "__main__":
    main()
