#!/usr/bin/env python3
"""Replace the video file of an existing Bilibili submission.

This is an explicit, account-mutating tool. It requires --confirm so normal
audits and dry-runs cannot accidentally edit an online submission.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
from pathlib import Path

from bilibili_api import Credential, user, video_uploader
from bilibili_api.utils.network import Api


SCRIPT_DIR = Path(__file__).parent
COOKIES_FILE = SCRIPT_DIR / "cookies.json"


def load_credential(cookies_file: Path = COOKIES_FILE) -> Credential:
    data = json.loads(cookies_file.read_text(encoding="utf-8"))
    cookies = {c["name"]: c["value"] for c in data["cookie_info"]["cookies"]}
    return Credential(
        sessdata=cookies.get("SESSDATA", ""),
        bili_jct=cookies.get("bili_jct", ""),
        buvid3=cookies.get("buvid3", ""),
        dedeuserid=cookies.get("DedeUserID", ""),
    )


async def fetch_archive_config(bvid: str, credential: Credential) -> dict:
    api = video_uploader._API["upload_args"]
    return await Api(**api, credential=credential).update_params(bvid=bvid).result


def build_edit_payload(config: dict, uploaded_page: dict) -> dict:
    archive = config["archive"]
    old_videos = config["videos"]
    if len(old_videos) != 1:
        raise ValueError(f"暂只支持单 P 替换，当前稿件有 {len(old_videos)} 个分 P")

    old_page = old_videos[0]
    return {
        "act_reserve_create": 0,
        "copyright": archive.get("copyright", 2),
        "source": archive.get("source") or "",
        "cover": archive.get("cover") or "",
        "desc": archive.get("desc") or "",
        "desc_format_id": archive.get("desc_format_id", 0),
        "dynamic": archive.get("dynamic") or "",
        "interactive": archive.get("interactive", 0),
        "no_reprint": archive.get("no_reprint", 0),
        "open_elec": 0,
        "origin_state": config.get("origin_state", 0),
        "subtitles": {"lan": "", "open": 0},
        "tag": archive.get("tag") or "英语学习,AI",
        "tid": archive.get("tid", 95),
        "title": archive.get("title", "")[:80],
        "up_close_danmaku": False,
        "up_close_reply": False,
        "up_selection_reply": bool(config.get("reply", {}).get("up_selection", False)),
        "videos": [
            {
                "title": old_page.get("title") or Path(uploaded_page["path"]).stem,
                "desc": old_page.get("desc") or "",
                "filename": uploaded_page["filename"],
                "cid": uploaded_page["cid"],
            }
        ],
        "web_os": 2,
    }


async def upload_replacement_page(video_path: Path, title: str, credential: Credential) -> dict:
    page = video_uploader.VideoUploaderPage(str(video_path), title=title)
    cover_placeholder = video_path.with_name(f"{video_path.stem}_replace_cover.jpg")
    if not cover_placeholder.exists():
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                "5",
                "-i",
                str(video_path),
                "-vframes",
                "1",
                "-update",
                "1",
                str(cover_placeholder),
            ],
            capture_output=True,
            check=False,
        )
    uploader = video_uploader.VideoUploader(
        pages=[page],
        meta={"title": title, "tag": "英语学习,AI", "tid": 95},
        credential=credential,
        cover=str(cover_placeholder),
    )
    uploader.line = await video_uploader._choose_line(None)
    data = await uploader._upload_page(page)
    return {"path": str(video_path), **data}


async def submit_edit(bvid: str, payload: dict, credential: Credential) -> dict:
    api = video_uploader._API["edit"]
    payload = dict(payload)
    payload["csrf"] = credential.bili_jct
    params = {"csrf": credential.bili_jct}
    headers = {
        "content-type": "application/json;charset=UTF-8",
        "referer": "https://member.bilibili.com",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
    }
    payload["aid"] = video_uploader.bvid2aid(bvid)
    return (
        await Api(**api, credential=credential, no_csrf=True, json_body=True)
        .update_params(**params)
        .update_data(**payload)
        .update_headers(**headers)
        .result
    )


async def replace_video(args: argparse.Namespace) -> None:
    video_path = Path(args.video).expanduser().resolve()
    if not video_path.exists():
        raise FileNotFoundError(video_path)

    credential = load_credential()
    self_info = await user.get_self_info(credential)
    print(f"登录有效: {self_info['name']} (UID: {self_info['mid']})")

    config = await fetch_archive_config(args.bvid, credential)
    archive = config["archive"]
    print(f"目标稿件: {args.bvid} / {archive.get('title', '')}")
    print(f"新文件: {video_path} ({video_path.stat().st_size / 1024 / 1024:.1f} MB)")

    if not args.confirm:
        print("DRY RUN: 未上传、未替换。加 --confirm 才会修改线上稿件。")
        return

    uploaded_page = await upload_replacement_page(
        video_path, title=Path(video_path).stem, credential=credential
    )
    print(f"新分 P 已上传: filename={uploaded_page['filename']} cid={uploaded_page['cid']}")

    payload = build_edit_payload(config, uploaded_page)
    result = await submit_edit(args.bvid, payload, credential)
    print(f"替换提交完成: {result}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Replace a Bilibili submission video file")
    parser.add_argument("bvid", help="Existing Bilibili BVID")
    parser.add_argument("video", help="Replacement mp4 path")
    parser.add_argument("--confirm", action="store_true", help="Actually upload and submit edit")
    args = parser.parse_args()
    asyncio.run(replace_video(args))


if __name__ == "__main__":
    main()
