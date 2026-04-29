# youtube-to-bili

YouTube 视频自动下载 → 双语字幕（中英）→ 上传 B 站流水线。

## 目录结构

```
youtube-to-bili/
├── pipeline.sh          # 主流程：下载 → 翻译 → 压制字幕 → 上传
├── parse_vtt.py         # 解析 YouTube VTT（逐词时间戳）→ SRT
├── translate.py         # 批量翻译（hermes chat -q ... -Q）
├── make_ass.py          # 生成双语 ASS 字幕（英文白色，中文白色粗体）
├── bili_upload_v2.py    # B站上传
├── merge_srt.py         # 旧版 SRT 合并（备用）
├── cookies.json         # B站 cookies（不入 git，需手动放置）
├── downloads/           # 下载的视频（不入 git）
├── subtitles/           # 字幕文件（不入 git）
├── output/              # 压制后视频（不入 git）
└── uploaded/            # 上传记录 history.json（不入 git）
```

## 依赖

```bash
brew install yt-dlp ffmpeg-full
pip install requests
```

翻译依赖 `hermes` CLI（需已配置）。
B站上传依赖 `cookies.json`（从浏览器导出，Netscape 格式）。

## 快速使用

### 单个视频

```bash
./pipeline.sh "https://www.youtube.com/watch?v=VIDEO_ID"
```

流程：
1. 用 `yt-dlp` 下载视频 + 英文 VTT 字幕
2. `parse_vtt.py` 解析逐词时间戳 → `en.srt`
3. `translate.py` 翻译 → `zh.srt`（每批30行，hermes chat）
4. `make_ass.py` 合并 → 双语 ASS 字幕
5. `ffmpeg` 压制字幕进视频
6. `bili_upload_v2.py` 上传 B 站

### 字幕样式

- 英文：白色，Arial 28px，底部
- 中文：白色粗体，PingFang SC 32px，英文下方
- 代理：`http://127.0.0.1:7897`（clash/v2ray）

## 环境变量 / 配置

目前配置硬编码在各脚本中，主要参数：

| 参数 | 位置 | 默认值 |
|------|------|--------|
| 代理 | `pipeline.sh` / `translate.py` | `http://127.0.0.1:7897` |
| 翻译批次大小 | `translate.py` BATCH_SIZE | 30 |
| 字幕字号 | `make_ass.py` | EN=28, ZH=32 |
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

## 定时任务

每天 9:00 AM 自动跑：
- 长视频：Michael Singer 播放列表（倒序，取最新未翻译）
  - `https://www.youtube.com/playlist?list=PLyOuAoSmZkKoESr2acNWwhznusbBkKXsT`
- 短视频：Adyashanti Shorts
  - `https://www.youtube.com/@Adyashanti/shorts`

## 注意事项

- `cookies.json` 不入 git，需手动配置
- B 站新账号建议每天不超过 2 个视频，避免风控
- VTT 字幕比 SRT 时间精度更高，优先用 VTT；无 VTT 时降级用 Whisper
- `make_ass.py` 会自动跳过 start ≥ end 的无效字幕行
- HTML 实体（`&gt;` 等）在 `parse_vtt.py` 中已 unescape 处理
