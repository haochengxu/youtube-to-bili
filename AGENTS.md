# YouTube → B站 双语字幕流水线

## 项目目标
给定 YouTube 视频链接，自动完成：下载视频+字幕 → 翻译字幕 → 合并双语硬字幕 → 准备上传 B 站

## 目录结构
```
~/youtube-to-bili/
├── input/          # URL 列表文件
├── downloads/      # yt-dlp 下载的原始文件
├── subtitles/      # 处理后的字幕文件
├── output/         # 压制完成的成品视频
├── uploaded/       # 已上传归档
├── config/         # 配置文件
├── pipeline.sh     # 主流程脚本（入口）
└── translate.py    # 字幕翻译脚本
```

## 技术选型（已确定，不要更改）
- **下载**: yt-dlp
- **转录兜底**: whisper（本地，base model）
- **翻译**: Codex CLI（`Codex -p`，pipe 模式）
- **字幕格式**: ASS 双语（英上中下，英文白色，中文黄色，苹方字体）
- **压制**: ffmpeg，libx264 crf 18
- **上传**: biliup（需要用户手动扫码登录，脚本不自动触发登录）

## 主要脚本要求

### pipeline.sh
- 接受一个 YouTube URL 作为参数：`./pipeline.sh "https://youtube.com/watch?v=xxx"`
- 步骤：下载 → 检查字幕（没有则 Whisper）→ 翻译 → 生成 ASS → 压制
- 每步有清晰的日志输出
- 失败时给出友好的错误提示

### translate.py
- 读取英文 SRT 文件路径作为参数
- 调用 `Codex -p` 批量翻译（每批 50 条字幕）
- 保留原始时间码，只替换文本
- 输出中文 SRT 文件（同目录，`.zh.srt` 后缀）

### make_ass.py
- 读取英文 SRT + 中文 SRT
- 生成双语 ASS 文件
- 英文：Arial 26px，白色，描边黑色，位置在下方偏上
- 中文：苹方 30px，黄色，描边黑色，位置在最下方
- 兼容 macOS 苹方字体名称（PingFang SC）

## 注意事项
- 所有脚本要有 shebang 和执行权限说明
- Python 用 python3
- 兼容 macOS（arm64，Homebrew 路径 /opt/homebrew）
- yt-dlp 和 ffmpeg 通过 brew 安装
- whisper 通过 `pip install openai-whisper` 安装
- biliup 上传命令单独提供，不集成进 pipeline.sh（避免自动上传）
