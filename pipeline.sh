#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────
# YouTube → B站 双语字幕流水线
# 用法: ./pipeline.sh "https://youtube.com/watch?v=xxx"
# ──────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOADS="$SCRIPT_DIR/downloads"
SUBTITLES="$SCRIPT_DIR/subtitles"
OUTPUT="$SCRIPT_DIR/output"

# Homebrew 路径（Apple Silicon）
export PATH="/opt/homebrew/bin:$PATH"

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
err()  { echo "[ERROR] $*" >&2; exit 1; }

# ── 参数检查 ──────────────────────────────────
[[ $# -lt 1 ]] && err "用法: $0 \"<YouTube URL>\""
URL="$1"

# ── 步骤 1: 下载视频 + 字幕 ───────────────────
log "▶ 步骤 1/5：下载视频和字幕"

yt-dlp \
  --write-subs \
  --write-auto-subs \
  --sub-langs "en.*" \
  --sub-format "vtt" \
  --skip-download \
  -o "$DOWNLOADS/%(id)s.%(ext)s" \
  "$URL" || true   # 字幕可能没有，先不 fatal

VIDEO_FILE=$(yt-dlp \
  --get-filename \
  -o "$DOWNLOADS/%(id)s.%(ext)s" \
  "$URL" 2>/dev/null)

VIDEO_ID=$(yt-dlp --get-id "$URL" 2>/dev/null)
log "视频 ID: $VIDEO_ID"

log "下载视频..."
yt-dlp \
  -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" \
  -o "$DOWNLOADS/%(id)s.%(ext)s" \
  "$URL"

VIDEO_FILE=""
for _ext in mp4 mkv webm; do
  [[ -f "$DOWNLOADS/${VIDEO_ID}.${_ext}" ]] && VIDEO_FILE="$DOWNLOADS/${VIDEO_ID}.${_ext}" && break
done
[[ -z "$VIDEO_FILE" ]] && err "找不到下载的视频文件（ID: $VIDEO_ID）"
log "视频文件: $VIDEO_FILE"

# ── 步骤 2: 找字幕，没有则 Whisper 转录 ─────────
log "▶ 步骤 2/5：检查字幕"

EN_SRT=""
EN_VTT=""

# 优先查找 VTT（有逐词精确时间戳）
for _name in "${VIDEO_ID}.en.vtt" "${VIDEO_ID}.en-orig.vtt" "${VIDEO_ID}.en-US.vtt"; do
  [[ -f "$DOWNLOADS/$_name" ]] && EN_VTT="$DOWNLOADS/$_name" && break
done

if [[ -n "$EN_VTT" ]]; then
  log "找到 VTT 字幕: ${EN_VTT}（使用精确逐词时间戳）"
  python3 "$SCRIPT_DIR/parse_vtt.py" "$EN_VTT" "$SUBTITLES/${VIDEO_ID}.en.srt"
else
  # fallback: 找 SRT
  for _name in "${VIDEO_ID}.en.srt" "${VIDEO_ID}.en-orig.srt" "${VIDEO_ID}.en-US.srt"; do
    [[ -f "$DOWNLOADS/$_name" ]] && EN_SRT="$DOWNLOADS/$_name" && break
  done

  if [[ -n "$EN_SRT" ]]; then
    log "找到 SRT 字幕（无精确时间戳，将用 merge_srt 合并）: $EN_SRT"
    cp "$EN_SRT" "$SUBTITLES/${VIDEO_ID}.en.srt"
    python3 "$SCRIPT_DIR/merge_srt.py" "$SUBTITLES/${VIDEO_ID}.en.srt" "$SUBTITLES/${VIDEO_ID}.en.srt"
  else
    log "未找到字幕，使用 Whisper 转录..."
    command -v whisper >/dev/null 2>&1 || err "whisper 未安装，运行: pip install openai-whisper"
    whisper "$VIDEO_FILE" \
      --model small \
      --language en \
      --output_format srt \
      --output_dir "$SUBTITLES"
    WHISPER_OUT="$SUBTITLES/$(basename "${VIDEO_FILE%.*}").srt"
    [[ -f "$WHISPER_OUT" ]] || err "Whisper 转录失败，未生成 SRT 文件"
    mv "$WHISPER_OUT" "$SUBTITLES/${VIDEO_ID}.en.srt"
  fi
fi

EN_SRT="$SUBTITLES/${VIDEO_ID}.en.srt"
log "英文字幕: $EN_SRT"

# ── 步骤 3: 翻译字幕 ──────────────────────────
log "▶ 步骤 3/5：翻译字幕（英→中）"

ZH_SRT="$SUBTITLES/${VIDEO_ID}.zh.srt"
if [[ -f "$ZH_SRT" ]]; then
  log "中文字幕已存在，跳过翻译: $ZH_SRT"
else
  python3 "$SCRIPT_DIR/translate.py" "$EN_SRT"
  [[ -f "$ZH_SRT" ]] || err "翻译失败，未生成中文字幕"
fi
log "中文字幕: $ZH_SRT"

# ── 步骤 4: 生成双语 ASS 字幕 ─────────────────
log "▶ 步骤 4/5：生成双语 ASS 字幕"

ASS_FILE="$SUBTITLES/${VIDEO_ID}.bilingual.ass"

# 检测视频分辨率
VID_WIDTH=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of csv=p=0 "$VIDEO_FILE" 2>/dev/null)
VID_HEIGHT=$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of csv=p=0 "$VIDEO_FILE" 2>/dev/null)
VID_WIDTH=${VID_WIDTH:-1920}
VID_HEIGHT=${VID_HEIGHT:-1080}
log "视频分辨率: ${VID_WIDTH}x${VID_HEIGHT}"

python3 "$SCRIPT_DIR/make_ass.py" "$EN_SRT" "$ZH_SRT" "$ASS_FILE" "$VID_WIDTH" "$VID_HEIGHT"
[[ -f "$ASS_FILE" ]] || err "make_ass.py 未生成 ASS 文件"
log "ASS 字幕: $ASS_FILE"

# ── 步骤 5: 压制硬字幕视频 ────────────────────
log "▶ 步骤 5/5：压制硬字幕视频（crf 18）"

OUT_FILE="$OUTPUT/${VIDEO_ID}.mp4"
# ffmpeg filtergraph 中 ':' 和 '\' 需要转义
ffmpeg -y \
  -i "$VIDEO_FILE" \
  -vf "ass=${ASS_FILE}" \
  -c:v libx264 -crf 18 -preset slow \
  -c:a aac -b:a 192k \
  "$OUT_FILE"

[[ -f "$OUT_FILE" ]] || err "ffmpeg 压制失败"
log "✅ 完成！成品视频: $OUT_FILE"
log ""
log "上传到 B站请手动运行（需先扫码登录）："
log "  biliup upload \"$OUT_FILE\""
