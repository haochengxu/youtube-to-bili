#!/usr/bin/env python3
"""
YouTube → B站自动搬运队列管理系统

队列文件: ~/youtube-to-bili/queue.json
频道配置: ~/youtube-to-bili/channels.json

用法:
  python3 queue_manager.py scan              # 扫描订阅频道，新视频加入队列
  python3 queue_manager.py add <url>          # 手动添加视频到队列
  python3 queue_manager.py add-playlist <url> # 添加整个播放列表
  python3 queue_manager.py next              # 获取下一个待处理视频
  python3 queue_manager.py status            # 查看队列状态
  python3 queue_manager.py mark <video_id> <status>  # 标记视频状态
  python3 queue_manager.py list [status]     # 列出指定状态的视频
"""
import json
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path

BASE_DIR = Path.home() / "youtube-to-bili"
QUEUE_FILE = BASE_DIR / "queue.json"
CHANNELS_FILE = BASE_DIR / "channels.json"

# 状态流转: pending → downloading → translating → uploading → done
# 失败状态: failed
VALID_STATUSES = ["pending", "downloading", "translating", "uploading", "done", "failed", "skipped"]


def load_queue():
    if QUEUE_FILE.exists():
        with open(QUEUE_FILE) as f:
            return json.load(f)
    return {"videos": [], "last_scan": None}


def save_queue(queue):
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)


def load_channels():
    if CHANNELS_FILE.exists():
        with open(CHANNELS_FILE) as f:
            return json.load(f)
    return {"channels": []}


def get_video_ids_in_queue(queue):
    return {v["video_id"] for v in queue["videos"]}


def add_video(queue, video_id, title, channel_name, bili_folder, source_url, duration=None, playlist_index=None):
    """Add a video to the queue if not already present."""
    existing_ids = get_video_ids_in_queue(queue)
    if video_id in existing_ids:
        return False
    
    entry = {
        "video_id": video_id,
        "title": title,
        "channel_name": channel_name,
        "bili_folder": bili_folder,
        "source_url": source_url,
        "duration": duration,
        "status": "pending",
        "added_at": datetime.now().isoformat(),
        "processed_at": None,
        "bili_bvid": None,
        "error": None,
        "playlist_index": playlist_index,
    }
    queue["videos"].append(entry)
    return True


def cmd_scan(queue):
    """Scan subscribed channels for new videos."""
    channels = load_channels()
    total_new = 0
    
    for ch in channels.get("channels", []):
        print(f"\n📡 扫描频道: {ch['name']}")
        playlist_url = ch.get("playlist_url", ch.get("channel_url", ""))
        if not playlist_url:
            print(f"  ⚠️ 没有 playlist_url，跳过")
            continue
        
        try:
            result = subprocess.run(
                ["yt-dlp", "--flat-playlist", "--print", "%(title)s\t%(id)s\t%(duration)s",
                 playlist_url],
                capture_output=True, text=True, timeout=120
            )
            lines = [l for l in result.stdout.strip().split("\n") if l and "\t" in l]
            
            existing = get_video_ids_in_queue(queue)
            new_count = 0
            for i, line in enumerate(lines):
                parts = line.split("\t")
                if len(parts) >= 2:
                    title, vid = parts[0], parts[1]
                    duration = float(parts[2]) if len(parts) > 2 and parts[2] != "NA" else None
                    
                    # Skip private/deleted videos
                    if "[Private" in title or "[Deleted" in title:
                        continue
                    
                    if vid not in existing:
                        url = f"https://www.youtube.com/watch?v={vid}"
                        add_video(queue, vid, title, ch["name"], ch.get("bili_folder", ""),
                                  url, duration, playlist_index=i)
                        new_count += 1
            
            total_new += new_count
            print(f"  ✅ 发现 {new_count} 个新视频（共 {len(lines)} 个）")
            
        except subprocess.TimeoutExpired:
            print(f"  ❌ 超时")
        except Exception as e:
            print(f"  ❌ 错误: {e}")
    
    queue["last_scan"] = datetime.now().isoformat()
    save_queue(queue)
    print(f"\n总计新增 {total_new} 个视频到队列")
    return total_new


def cmd_add(queue, url):
    """Add a single video URL to queue."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--print", "%(title)s\t%(id)s\t%(channel)s\t%(duration)s", "--no-download", url],
            capture_output=True, text=True, timeout=60
        )
        parts = result.stdout.strip().split("\t")
        if len(parts) >= 3:
            title, vid, channel = parts[0], parts[1], parts[2]
            duration = float(parts[3]) if len(parts) > 3 and parts[3] != "NA" else None
            if add_video(queue, vid, title, channel, "", url, duration):
                save_queue(queue)
                print(f"✅ 已添加: {title} ({vid})")
            else:
                print(f"⚠️ 已在队列中: {title} ({vid})")
        else:
            print(f"❌ 无法获取视频信息: {result.stderr}")
    except Exception as e:
        print(f"❌ 错误: {e}")


def cmd_add_playlist(queue, url, channel_name="", bili_folder=""):
    """Add all videos from a playlist to queue."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--print", "%(title)s\t%(id)s\t%(duration)s", url],
            capture_output=True, text=True, timeout=120
        )
        lines = [l for l in result.stdout.strip().split("\n") if l and "\t" in l]
        
        added = 0
        # Reverse so oldest videos are processed first
        for i, line in enumerate(reversed(lines)):
            parts = line.split("\t")
            if len(parts) >= 2:
                title, vid = parts[0], parts[1]
                duration = float(parts[2]) if len(parts) > 2 and parts[2] != "NA" else None
                
                if "[Private" in title or "[Deleted" in title:
                    continue
                
                video_url = f"https://www.youtube.com/watch?v={vid}"
                if add_video(queue, vid, title, channel_name, bili_folder, video_url, duration, playlist_index=len(lines)-1-i):
                    added += 1
        
        save_queue(queue)
        print(f"✅ 添加了 {added} 个视频（共 {len(lines)} 个，{len(lines)-added} 个已存在或被跳过）")
    except Exception as e:
        print(f"❌ 错误: {e}")


def cmd_next(queue):
    """Get the next pending video."""
    for v in queue["videos"]:
        if v["status"] == "pending":
            print(json.dumps(v, ensure_ascii=False, indent=2))
            return v
    print("队列中没有待处理的视频")
    return None


def cmd_mark(queue, video_id, status, bvid=None, error=None):
    """Mark a video's status."""
    if status not in VALID_STATUSES:
        print(f"❌ 无效状态: {status}，可选: {VALID_STATUSES}")
        return
    
    for v in queue["videos"]:
        if v["video_id"] == video_id:
            v["status"] = status
            if status == "done":
                v["processed_at"] = datetime.now().isoformat()
            if bvid:
                v["bili_bvid"] = bvid
            if error:
                v["error"] = error
            save_queue(queue)
            print(f"✅ {video_id} → {status}")
            return
    print(f"❌ 未找到视频: {video_id}")


def cmd_status(queue):
    """Print queue status summary."""
    from collections import Counter
    counts = Counter(v["status"] for v in queue["videos"])
    total = len(queue["videos"])
    print(f"📊 队列状态 (共 {total} 个视频)")
    print(f"  ⏳ pending:      {counts.get('pending', 0)}")
    print(f"  ⬇️ downloading:  {counts.get('downloading', 0)}")
    print(f"  🔄 translating:  {counts.get('translating', 0)}")
    print(f"  ⬆️ uploading:    {counts.get('uploading', 0)}")
    print(f"  ✅ done:         {counts.get('done', 0)}")
    print(f"  ❌ failed:       {counts.get('failed', 0)}")
    print(f"  ⏭️ skipped:      {counts.get('skipped', 0)}")
    if queue.get("last_scan"):
        print(f"  📡 上次扫描: {queue['last_scan']}")


def cmd_list(queue, status=None):
    """List videos with optional status filter."""
    for v in queue["videos"]:
        if status is None or v["status"] == status:
            dur = f" ({int(v.get('duration', 0) or 0)//60}min)" if v.get("duration") else ""
            bv = f" → {v['bili_bvid']}" if v.get("bili_bvid") else ""
            print(f"  [{v['status']:12}] {v['title'][:60]}{dur}{bv}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    
    queue = load_queue()
    cmd = sys.argv[1]
    
    if cmd == "scan":
        cmd_scan(queue)
    elif cmd == "add" and len(sys.argv) >= 3:
        cmd_add(queue, sys.argv[2])
    elif cmd == "add-playlist" and len(sys.argv) >= 3:
        channel_name = sys.argv[3] if len(sys.argv) > 3 else ""
        bili_folder = sys.argv[4] if len(sys.argv) > 4 else ""
        cmd_add_playlist(queue, sys.argv[2], channel_name, bili_folder)
    elif cmd == "next":
        cmd_next(queue)
    elif cmd == "mark" and len(sys.argv) >= 4:
        bvid = sys.argv[4] if len(sys.argv) > 4 else None
        cmd_mark(queue, sys.argv[2], sys.argv[3], bvid)
    elif cmd == "status":
        cmd_status(queue)
    elif cmd == "list":
        status = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_list(queue, status)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
