# youtube-to-bili

YouTube 视频自动下载 → 双语字幕（中英）→ 学习摘要 → B 站发布准备流水线。

## 目录结构

```
youtube-to-bili/
├── pipeline.sh          # 主流程：下载 → 翻译 → 生成摘要 → 压制字幕
├── parse_vtt.py         # 解析 YouTube VTT（逐词时间戳）→ SRT
├── translate.py         # 批量翻译（TRANSLATOR=codex|copilot|hermes）
├── make_ass.py          # 生成双语 ASS 字幕（英文白色，中文黄色粗体）
├── detect_burned_subtitles.py # 检测短视频是否已有烧录英文字幕
├── summarize_subtitles.py # 生成学习摘要 Markdown
├── audit_uploaded.py    # 体检已上传视频的本地字幕/成品文件
├── COPILOT_TASKS.md     # 交给 Copilot/agent 的后续实现任务与验收标准
├── bili_upload_v2.py    # B站上传
├── merge_srt.py         # 旧版 SRT 合并（备用）
├── cookies.json         # B站 cookies（不入 git，需手动放置）
├── downloads/           # 下载的视频（不入 git）
├── subtitles/           # 字幕文件（不入 git）
├── output/              # 压制后视频（不入 git）
├── uploaded/history.json # 已上传记录（入 git）
```

## 依赖

```bash
brew install yt-dlp ffmpeg-full
pip install requests
```

翻译默认依赖 `Codex` CLI，也可通过 `TRANSLATOR=copilot` 切换到 Copilot。
B站上传依赖 `cookies.json`（从浏览器导出，Netscape 格式）。

## 快速使用

### 单个视频

```bash
./pipeline.sh "https://www.youtube.com/watch?v=VIDEO_ID"
```

流程：
1. 用 `yt-dlp` 下载视频 + 英文 VTT 字幕
2. `parse_vtt.py` 解析逐词时间戳 → `en.srt`
3. `translate.py` 翻译 → `zh.srt`（每批50行，默认 Codex）
4. `make_ass.py` 合并 → 双语 ASS 字幕
5. `summarize_subtitles.py` 生成学习摘要 → `summaries/{video_id}.md`
6. `ffmpeg` 压制字幕进视频
7. 输出 B 站上传命令，不自动真实上传

### 字幕样式

- 英文：白色，Arial 28px，底部
- 中文：黄色粗体，Heiti SC 32px，英文下方
- YouTube 代理：默认直连；需要时设置 `YOUTUBE_PROXY=http://127.0.0.1:7890`

## 环境变量 / 配置

目前配置硬编码在各脚本中，主要参数：

| 参数 | 位置 | 默认值 |
|------|------|--------|
| YouTube 代理 | `YOUTUBE_PROXY` | 空，默认直连 |
| yt-dlp 命令 | `YTDLP_CMD` | 自动探测 `yt-dlp`，再回退到当前 Python 的 `yt_dlp` 模块 |
| 翻译后端 | `TRANSLATOR` | `codex` |
| Codex 命令 | `CODEX_TRANSLATE_CMD` | `Codex exec --sandbox read-only --skip-git-repo-check -` |
| Copilot 命令 | `COPILOT_TRANSLATE_CMD` | `copilot -p` |
| 翻译批次大小 | `translate.py` BATCH_SIZE | 50 |
| 字幕模式 | `SUBTITLE_MODE` | `auto`（优先 YouTube VTT 逐词时间戳；无 VTT 时用 Whisper；可手动设为 `precise` 强制 Whisper 或 `fast` 优先 SRT） |
| 英文叠加字幕 | `SHOW_ENGLISH` | `auto`（横屏显示；竖屏若检测到烧录英文则隐藏，否则显示） |
| 字幕字号（横屏） | `make_ass.py` | EN=44, ZH=52 |
| 字幕字号（竖屏） | `make_ass.py` | EN=34, ZH=46（按宽度缩放） |
| 视频分辨率 | pipeline.sh yt-dlp | 1280x720 |

## 已上传视频

记录在 `uploaded/history.json`（本地维护，不入 git）：

```json
[
  {
    "video_id": "66lKbfFnweU",
    "bvid": "BV1X69xBbE6h",
    "title": "阿迪亚香提 Adyashanti｜住于觉醒与非住于觉醒 ...",
    "uploaded_at": "2026-04-29T..."
  }
]
```

### 替换已上传视频

已上传稿件的替换不要默认自动执行，只做本地信息准备：

1. 先运行 `python3 audit_uploaded.py` 找出需要重做的视频
2. 重跑 pipeline 生成新的 `output/{video_id}.mp4`
3. 运行 `python3 replace_bili_prepare.py VIDEO_ID` 输出替换清单
4. 人工到 B 站创作中心编辑/替换视频源

示例：

```bash
python3 replace_bili_prepare.py G8DJHg428rQ
```

该脚本只读取本地 `uploaded/history.json` 和 `output/{video_id}.mp4`，打印以下信息供人工替换使用：

- 本地成品视频路径
- 标题
- 描述（如果历史记录里有）
- tags（如果历史记录里有）
- 原始 YouTube 链接（如果历史记录里有）
- Bilibili bvid / aid（如果历史记录里有）

如果缺少 bvid / aid，脚本会明确提示需要手动在创作中心查找稿件。

## 学习摘要

- 完整字幕仍保留在 `subtitles/*.srt` 与 `subtitles/*.ass`
- 学习摘要输出到 `summaries/*.md`
- `summarize_subtitles.py` 复用 `translator_cli.py`，因此 `TRANSLATOR=codex|copilot|hermes` 与翻译脚本保持一致

示例：

```bash
python3 summarize_subtitles.py subtitles/r2q_VN5beLs.en.srt subtitles/r2q_VN5beLs.zh.srt
```

摘要内容默认只保留核心观点、关键词、简介和可选章节，不会原样输出完整 transcript。

## 后续开发任务

后续任务拆解记录在 `COPILOT_TASKS.md`，目前包括：

- B 站已上传视频替换的只读准备层
- 短视频是否叠加英文字幕的自动决策
- 面向学习使用的字幕总结 Markdown
- 多平台发布抽象，以及抖音 dry-run 支持

## 定时任务

每天 9:00 AM 自动跑：
- 长视频：Michael Singer 播放列表（倒序，取最新未翻译）
  - `https://www.youtube.com/playlist?list=PLyOuAoSmZkKoESr2acNWwhznusbBkKXsT`
- 短视频：Adyashanti Shorts
  - `https://www.youtube.com/@Adyashanti/shorts`

上线前可先确认候选，不运行 pipeline、不上传、不写 history：

```bash
python3 daily_run.py --dry-run
python3 daily_run.py --dry-run --long-only
python3 daily_run.py --dry-run --short-only
```

## 注意事项

- `cookies.json` 不入 git，需手动配置
- B 站新账号建议每天不超过 2 个视频，避免风控
- VTT 字幕比 SRT 时间精度更高，优先用 VTT；无 VTT 时降级用 Whisper
- `make_ass.py` 会自动跳过 start ≥ end 的无效字幕行
- HTML 实体（`&gt;` 等）在 `parse_vtt.py` 中已 unescape 处理
