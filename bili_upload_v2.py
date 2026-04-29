#!/usr/bin/env python3
"""Upload video to Bilibili using bilibili-api-python.
Usage: python3 bili_upload_v2.py <video_path> --title "title" --desc "desc" --tag "tag1,tag2" --source "url"
"""
import asyncio
import json
import os
import sys
import argparse

# bilibili-api-python
from bilibili_api import video_uploader, Credential

COOKIES_FILE = os.path.expanduser("~/youtube-to-bili/cookies.json")

def load_credential():
    with open(COOKIES_FILE) as f:
        data = json.load(f)
    cookies = {}
    for c in data["cookie_info"]["cookies"]:
        cookies[c["name"]] = c["value"]
    
    return Credential(
        sessdata=cookies.get("SESSDATA", ""),
        bili_jct=cookies.get("bili_jct", ""),
        buvid3=cookies.get("buvid3", ""),
        dedeuserid=cookies.get("DedeUserID", ""),
    )

async def upload(args):
    credential = load_credential()
    
    # Verify login
    from bilibili_api import user
    self_info = await user.get_self_info(credential)
    print(f"✅ 登录有效: {self_info['name']} (UID: {self_info['mid']})")
    
    # Prepare upload
    page = video_uploader.VideoUploaderPage(
        path=args.video,
        title=os.path.splitext(os.path.basename(args.video))[0],
        description=args.desc or "",
    )
    
    meta = {
        "act_reserve_create": 0,
        "copyright": 2,  # 转载
        "source": args.source,
        "desc": args.desc or "",
        "desc_format_id": 0,
        "dynamic": "",
        "interactive": 0,
        "no_reprint": 0,
        "open_elec": 0,
        "origin_state": 0,
        "subtitles": {"lan": "", "open": 0},
        "tag": args.tag or "英语学习,AI",
        "tid": args.tid,
        "title": args.title,
        "up_close_danmaku": False,
        "up_close_reply": False,
        "up_selection_reply": False,
        "videos": [page],
        "dtime": 0,
    }
    
    # Prepare cover
    cover_path = args.cover if hasattr(args, 'cover') and args.cover else ""
    
    uploader = video_uploader.VideoUploader(
        pages=[page],
        meta=meta,
        credential=credential,
        cover=cover_path if cover_path else None,
    )
    
    @uploader.on("__ALL__")
    async def on_event(data):
        print(f"  事件: {data}")
    
    print(f"\n开始上传: {args.video}")
    print(f"标题: {args.title}")
    print(f"分区: {args.tid}")
    print(f"来源: {args.source}")
    print()
    
    result = await uploader.start()
    print(f"\n✅ 上传成功！")
    print(f"结果: {result}")
    return result

def main():
    parser = argparse.ArgumentParser(description="Upload video to Bilibili")
    parser.add_argument("video", help="Video file path")
    parser.add_argument("--title", required=True, help="Video title")
    parser.add_argument("--desc", default="", help="Video description")
    parser.add_argument("--tag", default="英语学习,AI", help="Tags, comma separated")
    parser.add_argument("--source", default="", help="Source URL (for repost)")
    parser.add_argument("--tid", type=int, default=95, help="Category ID (default: 95 tech)")
    parser.add_argument("--cover", default="", help="Cover image path")
    args = parser.parse_args()
    
    asyncio.run(upload(args))

if __name__ == "__main__":
    main()
