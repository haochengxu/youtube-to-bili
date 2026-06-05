#!/usr/bin/env python3
"""
douyin_upload.py — 抖音创作者中心自动上传（Playwright 浏览器自动化）

抖音没有面向个人、可用于自动转发的官方上传 API（官方"视频投稿"能力面向企业、
需资质审核 + OAuth 授权）。所以走"创作者中心网页 + 持久登录态"方案，
本质上是给抖音做一个 biliup：扫码登录一次，之后自动传。

子命令：
  login                       弹出可见浏览器，用手机抖音 App 扫码登录，登录态持久化
  check                       检查登录态是否仍有效（headless）
  upload <video> --title ...  上传一个视频（登录态有效时）

登录态目录：~/youtube-to-bili/.douyin_profile/（已 gitignore，含敏感登录态）

注意：upload 的页面选择器需对着真实登录后的页面校准，先跑通 login 再说。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SCRIPT_DIR = Path(__file__).parent
PROFILE_DIR = SCRIPT_DIR / ".douyin_profile"
CREATOR_HOME = "https://creator.douyin.com/"
UPLOAD_URL = "https://creator.douyin.com/creator-micro/content/upload"

# 抖音登录后会种的会话 cookie，用它判断是否已登录
_SESSION_COOKIE_NAMES = ("sessionid", "sessionid_ss", "sid_tt")
# 降低 headless 自动化指纹
_STEALTH_ARGS = ["--disable-blink-features=AutomationControlled"]


def _logged_in(context) -> bool:
    for c in context.cookies():
        if c.get("name") in _SESSION_COOKIE_NAMES and c.get("value"):
            return True
    return False


def _open_context(p, headless: bool):
    return p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        args=_STEALTH_ARGS,
        viewport={"width": 1280, "height": 900},
    )


def cmd_login(timeout: int = 240) -> int:
    PROFILE_DIR.mkdir(exist_ok=True)
    with sync_playwright() as p:
        ctx = _open_context(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(CREATOR_HOME, wait_until="domcontentloaded")
        if _logged_in(ctx):
            print("✅ 已是登录态，无需重复扫码。")
            ctx.close()
            return 0
        print(">> 浏览器已打开。请用【手机抖音 App】扫码登录创作者中心。")
        print(f">> 我每 2 秒检测一次登录态，最多等 {timeout}s …", flush=True)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if _logged_in(ctx):
                print("✅ 登录成功！登录态已持久化到", PROFILE_DIR)
                time.sleep(2)  # 让 storage 落盘
                ctx.close()
                return 0
            time.sleep(2)
        print("❌ 超时仍未检测到登录。", file=sys.stderr)
        ctx.close()
        return 1


def cmd_check() -> int:
    if not PROFILE_DIR.exists():
        print("❌ 还没登录过（无 .douyin_profile）。先跑 login。", file=sys.stderr)
        return 1
    with sync_playwright() as p:
        ctx = _open_context(p, headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(CREATOR_HOME, wait_until="domcontentloaded")
        ok = _logged_in(ctx)
        ctx.close()
    print("✅ 登录态有效" if ok else "❌ 登录态失效，需重新 login")
    return 0 if ok else 1


POST_URL_GLOB = "**/content/post/video**"


def cmd_upload(video: str, title: str, tags: list[str], headless: bool,
               draft: bool = False, upload_timeout: int = 600) -> int:
    video_path = Path(video).resolve()
    if not video_path.exists():
        print(f"❌ 视频不存在: {video_path}", file=sys.stderr)
        return 1
    if not PROFILE_DIR.exists():
        print("❌ 未登录，先跑 login。", file=sys.stderr)
        return 1

    with sync_playwright() as p:
        ctx = _open_context(p, headless=headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(UPLOAD_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        if not _logged_in(ctx):
            print("❌ 登录态失效，重新 login。", file=sys.stderr)
            ctx.close()
            return 1

        # 1. 投喂文件 → 跳到编辑页
        print(f"投喂文件: {video_path.name}", flush=True)
        page.set_input_files("input[type=file]", str(video_path))
        try:
            page.wait_for_url(POST_URL_GLOB, timeout=60000)
        except Exception:
            print("❌ 上传后未跳到编辑页（可能风控/页面变更）。", file=sys.stderr)
            ctx.close()
            return 1
        page.wait_for_timeout(3000)

        # 2. 标题
        t = title.strip()[:55]
        ti = page.query_selector("input[placeholder*='填写作品标题']")
        if ti:
            ti.click()
            ti.fill(t)
            print(f"标题: {t}")
        else:
            print("⚠️ 没找到标题输入框，跳过标题", file=sys.stderr)

        # 3. 话题（写进描述 contenteditable）
        if tags:
            desc = page.query_selector("div.zone-container[contenteditable='true']") \
                or page.query_selector("[contenteditable='true']")
            if desc:
                desc.click()
                page.keyboard.type(" " + " ".join(f"#{x.lstrip('#')}" for x in tags))
                print(f"话题: {tags}")

        # 4. 等上传到 100%（出现“上传成功”/“重新上传”，否则发布会失败）
        print(f"等待上传完成（最多 {upload_timeout}s）…", flush=True)
        done = False
        deadline = time.time() + upload_timeout
        while time.time() < deadline:
            body = page.inner_text("body")
            if ("上传成功" in body) or ("重新上传" in body):
                done = True
                break
            page.wait_for_timeout(3000)
        if not done:
            print("⚠️ 没等到明确的“上传成功”，仍尝试继续（可能失败）", file=sys.stderr)

        # 5. 发布 or 暂存草稿
        action = "暂存离开" if draft else "发布"
        page.wait_for_timeout(1500)
        try:
            page.get_by_role("button", name=action, exact=True).first.click()
        except Exception as exc:
            print(f"❌ 点击“{action}”失败: {exc}", file=sys.stderr)
            page.screenshot(path="/tmp/dy_upload_fail.png")
            ctx.close()
            return 1

        # 6. 等结果（草稿/发布后通常跳到内容管理页或弹提示）
        page.wait_for_timeout(6000)
        print(f"✅ 已点击“{action}”。当前页: {page.url}")
        page.screenshot(path="/tmp/dy_upload_result.png")
        print("结果截图: /tmp/dy_upload_result.png")
        ctx.close()
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="抖音创作者中心自动上传")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("login", help="扫码登录并持久化登录态")
    pl.add_argument("--timeout", type=int, default=240)

    sub.add_parser("check", help="检查登录态是否有效")

    pu = sub.add_parser("upload", help="上传一个视频")
    pu.add_argument("video")
    pu.add_argument("--title", required=True)
    pu.add_argument("--tags", nargs="*", default=[])
    pu.add_argument("--draft", action="store_true", help="存草稿（暂存离开），不公开发布")
    pu.add_argument("--show", action="store_true", help="可见浏览器（调试/避风控）")

    args = ap.parse_args()
    if args.cmd == "login":
        return cmd_login(timeout=args.timeout)
    if args.cmd == "check":
        return cmd_check()
    if args.cmd == "upload":
        return cmd_upload(args.video, args.title, args.tags,
                          headless=not args.show, draft=args.draft)
    return 1


if __name__ == "__main__":
    sys.exit(main())
