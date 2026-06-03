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
SUMMARIES="$SCRIPT_DIR/summaries"
SUBTITLE_MODE_REQUESTED="${SUBTITLE_MODE:-auto}"  # auto|fast|precise
SHOW_ENGLISH_REQUESTED="${SHOW_ENGLISH:-auto}"

# Homebrew 路径（Apple Silicon）
export PATH="/opt/homebrew/bin:$PATH"
if [[ -x "$SCRIPT_DIR/.venv/bin/python3" ]]; then
  export PATH="$SCRIPT_DIR/.venv/bin:$PATH"
fi

# nvm node 路径（yt-dlp 需要 node 来解 YouTube n challenge）
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh" 2>/dev/null
export PATH="/usr/local/bin:$PATH"

# yt-dlp 统一参数。优先 YTDLP_CMD，其次 PATH 中的 yt-dlp，最后回退当前 Python 模块。
YOUTUBE_PROXY="${YOUTUBE_PROXY:-}"
YTDLP_COMMON=(--js-runtimes node --remote-components ejs:github)
YTDLP_BASE=()
if [[ -n "${YTDLP_CMD:-}" ]]; then
  # shellcheck disable=SC2206
  YTDLP_BASE=(${YTDLP_CMD})
elif command -v yt-dlp >/dev/null 2>&1; then
  YTDLP_BASE=(yt-dlp)
elif python3 -m yt_dlp --version >/dev/null 2>&1; then
  YTDLP_BASE=(python3 -m yt_dlp)
else
  echo "[ERROR] 找不到可用的 yt-dlp。请安装 yt-dlp，或设置 YTDLP_CMD。" >&2
  exit 1
fi

YTDLP_NET_ARGS=(--cookies-from-browser chrome)
if [[ -n "$YOUTUBE_PROXY" ]]; then
  YTDLP_NET_ARGS+=(--proxy "$YOUTUBE_PROXY")
fi

ytdlp() {
  "${YTDLP_BASE[@]}" "${YTDLP_COMMON[@]}" "$@"
}

log()  { echo "[$(date '+%H:%M:%S')] $*"; }
err()  { echo "[ERROR] $*" >&2; exit 1; }

# ── 参数检查 ──────────────────────────────────
[[ $# -lt 1 ]] && err "用法: $0 \"<YouTube URL>\""
URL="$1"
mkdir -p "$DOWNLOADS" "$SUBTITLES" "$OUTPUT"
mkdir -p "$SUMMARIES"

# ── 步骤 1: 下载视频 + 字幕 ───────────────────
log "▶ 步骤 1/5：下载视频和字幕"

ytdlp \
  "${YTDLP_NET_ARGS[@]}" \
  --write-subs \
  --write-auto-subs \
  --sub-langs "en" \
  --sub-format "vtt/srt/best" \
  --skip-download \
  -o "$DOWNLOADS/%(id)s.%(ext)s" \
  "$URL" || true   # 字幕可能没有，先不 fatal

VIDEO_FILE=$(ytdlp \
  "${YTDLP_NET_ARGS[@]}" \
  --get-filename \
  -o "$DOWNLOADS/%(id)s.%(ext)s" \
  "$URL" 2>/dev/null)

VIDEO_ID=$(ytdlp "${YTDLP_NET_ARGS[@]}" --get-id "$URL" 2>/dev/null)
VIDEO_TITLE=$(ytdlp "${YTDLP_NET_ARGS[@]}" --get-title "$URL" 2>/dev/null || echo "")
log "视频 ID: $VIDEO_ID"

log "下载视频..."
ytdlp \
  "${YTDLP_NET_ARGS[@]}" \
  -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" \
  -o "$DOWNLOADS/%(id)s.%(ext)s" \
  "$URL"

VIDEO_FILE=""
for _ext in mp4 mkv webm; do
  [[ -f "$DOWNLOADS/${VIDEO_ID}.${_ext}" ]] && VIDEO_FILE="$DOWNLOADS/${VIDEO_ID}.${_ext}" && break
done
[[ -z "$VIDEO_FILE" ]] && err "找不到下载的视频文件（ID: $VIDEO_ID）"
log "视频文件: $VIDEO_FILE"
VID_DURATION_RAW=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$VIDEO_FILE" 2>/dev/null || echo "0")
VID_DURATION=$(python3 -c 'import sys; print(int(float(sys.argv[1] or 0)))' "$VID_DURATION_RAW" 2>/dev/null || echo "0")
SUBTITLE_MODE_CHOSEN=$(python3 "$SCRIPT_DIR/subtitle_mode.py" "$VID_DURATION" "$SUBTITLE_MODE_REQUESTED")
log "视频时长: ${VID_DURATION}s，字幕模式: ${SUBTITLE_MODE_CHOSEN}（请求: ${SUBTITLE_MODE_REQUESTED}）"

# ── 步骤 2: 找字幕，没有则 Whisper 转录 ─────────
log "▶ 步骤 2/5：检查字幕"

EN_SRT=""
EN_VTT=""

for _name in "${VIDEO_ID}.en.srt" "${VIDEO_ID}.en-orig.srt" "${VIDEO_ID}.en-US.srt"; do
  [[ -f "$DOWNLOADS/$_name" ]] && EN_SRT="$DOWNLOADS/$_name" && break
done

for _name in "${VIDEO_ID}.en.vtt" "${VIDEO_ID}.en-orig.vtt" "${VIDEO_ID}.en-US.vtt"; do
  [[ -f "$DOWNLOADS/$_name" ]] && EN_VTT="$DOWNLOADS/$_name" && break
done

# 合并重叠的时间段（传入视频宽度以自适应字幕长度）
VID_W=$(python3 "$SCRIPT_DIR/detect_content_width.py" "$VIDEO_FILE" 2>/dev/null || ffprobe -v error -select_streams v:0 -show_entries stream=width -of csv=p=0 "$VIDEO_FILE" 2>/dev/null)
VID_W=${VID_W:-1920}
log "  实际内容宽度: ${VID_W}px"

if [[ "$SUBTITLE_MODE_CHOSEN" == "auto" && -n "$EN_VTT" ]]; then
  log "找到 VTT 字幕: $EN_VTT"
  log "  自动模式：优先使用 YouTube VTT 逐词时间戳"
  python3 "$SCRIPT_DIR/parse_vtt.py" "$EN_VTT" "$SUBTITLES/${VIDEO_ID}.en.srt" "$VID_W"
elif [[ "$SUBTITLE_MODE_CHOSEN" == "auto" ]]; then
  log "  自动模式：未找到 VTT，使用 Whisper 词级时间戳"
  python3 "$SCRIPT_DIR/merge_srt_v2.py" "$VIDEO_FILE" "$SUBTITLES/${VIDEO_ID}.en.srt" "$VID_W"
elif [[ "$SUBTITLE_MODE_CHOSEN" == "precise" ]]; then
  log "  精修模式：使用 Whisper 词级时间戳"
  python3 "$SCRIPT_DIR/merge_srt_v2.py" "$VIDEO_FILE" "$SUBTITLES/${VIDEO_ID}.en.srt" "$VID_W"
elif [[ "$SUBTITLE_MODE_CHOSEN" == "fast" && -n "$EN_SRT" ]]; then
  log "找到 SRT 字幕: $EN_SRT"
  log "  快速模式：使用 YouTube SRT 断句"
  python3 "$SCRIPT_DIR/merge_srt.py" "$EN_SRT" "$SUBTITLES/${VIDEO_ID}.en.srt" "$VID_W"
elif [[ "$SUBTITLE_MODE_CHOSEN" == "fast" && -n "$EN_VTT" ]]; then
  log "找到 VTT 字幕: $EN_VTT"
  log "  快速模式：未找到 SRT，使用 YouTube VTT 逐词时间戳"
  python3 "$SCRIPT_DIR/parse_vtt.py" "$EN_VTT" "$SUBTITLES/${VIDEO_ID}.en.srt" "$VID_W"
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
log "▶ 步骤 4/6：生成双语 ASS 字幕"

ASS_FILE="$SUBTITLES/${VIDEO_ID}.bilingual.ass"

# 检测视频分辨率
VID_WIDTH=$(ffprobe -v error -select_streams v:0 -show_entries stream=width -of csv=p=0 "$VIDEO_FILE" 2>/dev/null)
VID_HEIGHT=$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of csv=p=0 "$VIDEO_FILE" 2>/dev/null)
VID_WIDTH=${VID_WIDTH:-1920}
VID_HEIGHT=${VID_HEIGHT:-1080}
log "视频分辨率: ${VID_WIDTH}x${VID_HEIGHT}"
ORIENTATION="horizontal"
[[ "$VID_HEIGHT" -gt "$VID_WIDTH" ]] && ORIENTATION="vertical"

BURNED_SUBTITLE_RESULT="skipped"
if [[ "$ORIENTATION" == "vertical" ]]; then
  BURNED_SUBTITLE_RESULT=$(python3 "$SCRIPT_DIR/detect_burned_subtitles.py" "$VIDEO_FILE" 2>/dev/null || echo "unknown")
fi

SHOW_ENGLISH_EFFECTIVE=$(python3 "$SCRIPT_DIR/subtitle_display.py" "$VID_WIDTH" "$VID_HEIGHT" "$SHOW_ENGLISH_REQUESTED" "$([[ "$BURNED_SUBTITLE_RESULT" == "skipped" ]] && echo "unknown" || echo "$BURNED_SUBTITLE_RESULT")")
log "英文字幕决策: orientation=${ORIENTATION}, detector=${BURNED_SUBTITLE_RESULT}, requested_SHOW_ENGLISH=${SHOW_ENGLISH_REQUESTED}, effective_SHOW_ENGLISH=${SHOW_ENGLISH_EFFECTIVE}"

python3 "$SCRIPT_DIR/make_ass.py" "$EN_SRT" "$ZH_SRT" "$ASS_FILE" "$VID_WIDTH" "$VID_HEIGHT" --show-english "$SHOW_ENGLISH_EFFECTIVE" --burned-subtitles "$([[ "$BURNED_SUBTITLE_RESULT" == "skipped" ]] && echo "unknown" || echo "$BURNED_SUBTITLE_RESULT")"
[[ -f "$ASS_FILE" ]] || err "make_ass.py 未生成 ASS 文件"
log "ASS 字幕: $ASS_FILE"

# ── 步骤 5: 压制硬字幕视频 ────────────────────
log "▶ 步骤 5/6：压制硬字幕视频（crf 18）"

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

# ── 步骤 6: 生成学习摘要 ──────────────────────
log "▶ 步骤 6/6：生成学习摘要"

SUMMARY_FILE="$SUMMARIES/${VIDEO_ID}.md"
if python3 "$SCRIPT_DIR/summarize_subtitles.py" "$EN_SRT" "$ZH_SRT" --title "$VIDEO_TITLE" --url "$URL"; then
  [[ -f "$SUMMARY_FILE" ]] && log "学习摘要: $SUMMARY_FILE"
else
  log "学习摘要生成失败，已保留成品视频，可稍后单独重跑 summarize_subtitles.py"
fi

# ── 后续：上传到 B站 ──────────────────────────
# 自动获取标题、简介、封面，用 bili_upload_v2.py 上传
EN_TITLE="$VIDEO_TITLE"
EN_DESC=$(ytdlp "${YTDLP_NET_ARGS[@]}" --get-description "$URL" 2>/dev/null | head -c 400 || echo "")

log ""
log "上传到 B站（python3 bili_upload_v2.py）："
log "  标题: $EN_TITLE"
log "  用法: python3 bili_upload_v2.py \"$OUT_FILE\" --title \"$EN_TITLE\" --desc \"...\" --source \"$URL\""
log ""
log "或通过 daily_run.py 自动上传（推荐）："
log "  python3 daily_run.py --url \"$URL\""
