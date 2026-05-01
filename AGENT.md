# Agent 操作指南

## 这个项目是什么
YouTube → B 站自动流水线。每天从 `channels.json` 的播放列表拉最新视频，下载 → 翻译双语字幕 → 压制 → 上传 B 站。

## 环境要求（另一台机器需手动配置）

```bash
brew install yt-dlp ffmpeg-full
pip3 install bilibili-api-python requests pillow
```

翻译用 `hermes` CLI（需已安装并配置好 API key）。

代理：`http://127.0.0.1:7897`（clash/v2ray，YouTube 和 B 站上传都需要）。

## 需要手动配置的文件

### 1. B 站 cookie（必须）
路径：`~/youtube-to-bili/cookies.json`

用 biliup 登录导出：
```bash
pip3 install biliup
biliup login
# 扫码后会生成 cookies.json
```

### 2. yt-dlp 用 Chrome cookie
所有 yt-dlp 命令都加了 `--cookies-from-browser chrome`，确保本机 Chrome 已登录 YouTube。

## 日常运行

```bash
cd ~/youtube-to-bili
python3 daily_run.py
```

每天 9:00 AM 自动跑（cron 已配置在原机器上，新机器需重新设）。

去重依据：`uploaded/history.json`（已在 git 里，clone 后即可用）。

## 已知坑

1. **长视频翻译慢**：5000条字幕约30分钟，不要在前台跑，用 `nohup` 或后台执行
2. **上传必须传 `--source`**：否则 B 站转载报错 21021
3. **标题/简介必须从 YouTube 原页面取**：`yt-dlp --get-title` + `--get-description`，不能自己编
4. **字幕字号**：横屏 EN=44/ZH=52，竖屏 EN=26/ZH=30（`make_ass.py` 自动判断）
5. **B 站风控**：每天不超过 2 个视频

## 订阅频道

见 `channels.json`。目前只有 Michael Singer Podcast 播放列表。

## 已上传记录

见 `uploaded/history.json`（git 追踪，会随每次上传更新）。
