#!/usr/bin/env python3
"""Upload video to Bilibili using web API directly.
Usage: python3 bili_upload.py <video_path> --title "title" --desc "desc" --tag "tag1,tag2" --source "url"
"""
import json
import os
import sys
import hashlib
import time
import urllib.request
import urllib.parse
import argparse

COOKIES_FILE = os.path.expanduser("~/youtube-to-bili/cookies.json")

def load_cookies():
    with open(COOKIES_FILE) as f:
        data = json.load(f)
    cookies = {}
    for c in data["cookie_info"]["cookies"]:
        cookies[c["name"]] = c["value"]
    return cookies

def make_cookie_header(cookies):
    return "; ".join(f"{k}={v}" for k, v in cookies.items())

def api_request(url, cookies, data=None, method="GET"):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Cookie": make_cookie_header(cookies),
        "Referer": "https://member.bilibili.com/platform/upload/video/frame",
    }
    if data is not None:
        if isinstance(data, dict):
            data = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method or "POST")
    else:
        req = urllib.request.Request(url, headers=headers, method=method)
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())

def check_login(cookies):
    """Verify cookies are valid by checking user info."""
    url = "https://api.bilibili.com/x/web-interface/nav"
    result = api_request(url, cookies)
    if result["code"] == 0:
        uname = result["data"]["uname"]
        mid = result["data"]["mid"]
        print(f"✅ 登录有效: {uname} (UID: {mid})")
        return True
    else:
        print(f"❌ 登录失败: {result}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Upload video to Bilibili")
    parser.add_argument("video", help="Video file path")
    parser.add_argument("--title", required=True, help="Video title")
    parser.add_argument("--desc", default="", help="Video description")
    parser.add_argument("--tag", default="", help="Tags, comma separated")
    parser.add_argument("--source", default="", help="Source URL (for repost)")
    parser.add_argument("--tid", type=int, default=95, help="Category ID (default: 95 tech)")
    parser.add_argument("--check-only", action="store_true", help="Only check login status")
    args = parser.parse_args()

    cookies = load_cookies()
    
    if args.check_only:
        check_login(cookies)
        return
    
    if not check_login(cookies):
        print("请重新登录")
        return

    print(f"\n准备上传: {args.video}")
    print(f"标题: {args.title}")
    print(f"分区: {args.tid}")
    
    # For now just verify login works
    print("\n⚠️ 直接 API 上传需要实现分片上传协议，比较复杂。")
    print("建议使用 bilibili-toolman 或直接在网页端上传。")

if __name__ == "__main__":
    main()
