# Agent 操作指南

## 这个项目是什么
YouTube → B 站自动流水线。每天从 `channels.json` 的播放列表拉最新视频，下载 → 翻译双语字幕 → 压制 → 上传 B 站。

## 环境要求（另一台机器需手动配置）

```bash
brew install yt-dlp ffmpeg-full
pip3 install bilibili-api-python requests pillow
```

翻译默认用 `Codex` CLI，也支持 `TRANSLATOR=copilot` 切到 Copilot。
如本机 Copilot CLI 参数不同，可设置 `COPILOT_TRANSLATE_CMD` 覆盖。

代理：`http://127.0.0.1:7890`（clash/v2ray，YouTube 和 B 站上传都需要）。

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
4. **字幕字号**：按视频宽度自适应缩放（`make_ass.py`），基准 1920px 横屏 EN=44/ZH=52，竖屏 EN=26/ZH=30
5. **B 站风控**：每天不超过 2 个视频
6. **代理端口**：`127.0.0.1:7890`（不是 7897）
7. **yt-dlp 需要 JS runtime**：`python3.11 -m yt_dlp --js-runtimes node --remote-components ejs:github`，否则 403
8. **B 站删视频需人机验证**：无法自动化，用户必须手动在创作者中心删除
9. **历史上传体检**：`python3 audit_uploaded.py` 可检查已上传视频对应的本地字幕、ASS 和成品文件
10. **字幕模式**：`SUBTITLE_MODE=auto` 默认按时长选择；>10 分钟用 fast（YouTube SRT 断句，不跑 Whisper），短视频用 precise（Whisper 词级时间戳）

## 待改进（TODO）

详细的 Copilot/agent 实现拆解见 `COPILOT_TASKS.md`。优先级建议：先做短视频英文字幕决策和学习总结，再做 B 站替换准备层，最后做多平台发布与抖音 dry-run。

### 高优先级

1. **merge_srt_v2.py 长视频超时**：Whisper 全量转录 50 分钟视频需要 15-20 分钟，cron job 会超时杀掉。已加 `SUBTITLE_MODE=auto|fast|precise`：
   - fast mode：仅用 YouTube SRT + 断句，不跑 Whisper
   - 阈值：视频 > 10 分钟用 fast mode，≤ 10 分钟用 Whisper
   - 待实测：长视频 fast mode 的实际时间轴是否可接受
   - YouTube SRT 虽然时间戳有 3-10s 延迟，但对长视频可接受

2. **bili_upload_v2.py 封面 bug**：ffmpeg 生成封面失败时 `cover_path=""`，传给 `VideoUploader` 会 `FileNotFoundError`。应加空值检查。

3. **daily_run.py --url 重跑全流水线**：应该能跳过已完成的步骤（如已下载、已翻译），只做上传。

### 低优先级

4. **history.json 应由 pipeline 自动维护**：目前靠外部脚本手动写入，容易遗漏。
5. **pipeline.sh 没有 timeout 保护**：ffmpeg 压制长视频可能跑 30+ 分钟，应根据视频时长动态设置 timeout。
6. **translate.py 翻译对齐偶尔失败**：批量翻译返回条目数不匹配时只有 warning，没有重试逻辑。

## 订阅频道

见 `channels.json`。目前只有 Michael Singer Podcast 播放列表。

## 已上传记录

见 `uploaded/history.json`（git 追踪，会随每次上传更新）。
