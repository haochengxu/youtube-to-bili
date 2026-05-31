#!/bin/bash
# run_daily.sh — daily_run.py 的无人值守包装层（给 launchd / 手动跑共用）
#
# 职责：
#   1. 固定 PATH（launchd 环境啥都没有，必须显式给 yt-dlp/ffmpeg/whisper/claude/node）
#   2. 加载 .env.local（含 CLAUDE_CODE_OAUTH_TOKEN、代理）
#   3. 清掉桌面 App 注入的 ANTHROPIC_API_KEY，避免覆盖订阅长效 token
#   4. 用装了 bilibili_api 的 homebrew python3 跑 daily_run.py
#   5. 输出 tee 到带时间戳的日志
#
# 用法：
#   ./run_daily.sh                # 跑一长一短（定时任务就跑这个）
#   ./run_daily.sh --dry-run      # 只看候选计划，验证用
#   ./run_daily.sh --short-only   # 只跑短视频
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. 固定 PATH：homebrew(yt-dlp/ffmpeg/whisper/python3) + node v22(claude) + 系统
export PATH="/Users/xuhaocheng/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:/Users/xuhaocheng/.nvm/versions/node/v22.22.0/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# 2. 加载密钥/代理（.env.local 已 gitignore）
if [[ -f "$SCRIPT_DIR/.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/.env.local"
  set +a
else
  echo "[FATAL] 缺少 .env.local —— 先 cp .env.local.example .env.local 并填入 CLAUDE_CODE_OAUTH_TOKEN" >&2
  exit 1
fi

# 3. 清掉会覆盖订阅 token 的 API key（桌面 App 才会注入，launchd 不会，但手动跑时在）
unset ANTHROPIC_API_KEY ANTHROPIC_BASE_URL

# 4. 日志
mkdir -p "$SCRIPT_DIR/logs"
LOG="$SCRIPT_DIR/logs/daily-$(date +%Y%m%d-%H%M%S).log"
echo "===== run_daily.sh $(date '+%F %T') args=[$*] =====" | tee "$LOG"

# 5. 用 homebrew python3（装了 bilibili_api）跑；daily_run 内部会先做代理+鉴权自检
/opt/homebrew/bin/python3 "$SCRIPT_DIR/daily_run.py" "$@" 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}

echo "===== 结束 exit=$rc 日志：$LOG =====" | tee -a "$LOG"
exit "$rc"
