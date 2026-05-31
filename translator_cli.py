#!/usr/bin/env python3
"""Shared LLM translation CLI adapter.

Environment:
  TRANSLATOR=claude|codex|copilot|hermes
  CLAUDE_TRANSLATE_CMD='claude -p --model sonnet'   # 想省钱改 --model haiku
  CODEX_TRANSLATE_CMD='Codex exec --sandbox read-only --skip-git-repo-check -'
  COPILOT_TRANSLATE_CMD='copilot -p'
  HERMES_TRANSLATE_CMD='hermes chat -q {prompt} -Q'
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time


DEFAULT_COMMANDS = {
    # pipe 模式：prompt 从 stdin 进，--model 选模型（sonnet 翻译质量/成本平衡最好）
    "claude": "claude -p --model sonnet",
    "codex": "Codex exec --sandbox read-only --skip-git-repo-check -",
    "copilot": "copilot -p {prompt}",
    "hermes": "hermes chat -q {prompt} -Q",
}


class TranslatorError(RuntimeError):
    pass


def _command_for_backend(backend: str) -> str:
    env_name = f"{backend.upper()}_TRANSLATE_CMD"
    return os.environ.get(env_name, DEFAULT_COMMANDS.get(backend, "")).strip()


def available_backends() -> str:
    return ", ".join(sorted(DEFAULT_COMMANDS))


def run_llm(
    prompt: str,
    timeout: int = 300,
    backend: str | None = None,
    retries: int = 3,
    retry_base_delay: float = 8.0,
) -> str:
    """Run the selected translation backend and return stdout.

    瞬时失败（CLI 非零退出 / 超时，多为速率限制或代理抖动）会按指数退避重试，
    避免一批字幕抽风就把整条流水线（已下载+转录完）拖垮。命令缺失则不重试。
    """
    selected = (backend or os.environ.get("TRANSLATOR") or "codex").strip().lower()
    command_template = _command_for_backend(selected)
    if not command_template:
        raise TranslatorError(
            f"未知翻译后端: {selected}. 可选: {available_backends()}"
        )

    if "{prompt}" in command_template:
        prompt_placeholder = "__PROMPT_PLACEHOLDER__"
        command = [
            prompt if part == prompt_placeholder else part
            for part in shlex.split(command_template.replace("{prompt}", prompt_placeholder))
        ]
        stdin = None
    else:
        command = shlex.split(command_template)
        stdin = prompt

    last_err = ""
    for attempt in range(1, retries + 2):  # 首次 + retries 次重试
        try:
            result = subprocess.run(
                command,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            # 命令不存在，重试也没用，直接抛
            raise TranslatorError(
                f"找不到翻译命令: {command[0]}，请安装或设置 {selected.upper()}_TRANSLATE_CMD"
            ) from exc
        except subprocess.TimeoutExpired:
            last_err = f"翻译超时（>{timeout}s）"
        else:
            if result.returncode == 0:
                return result.stdout.strip()
            # 非零退出：claude 的真实报错有时在 stdout，两边都收进来
            last_err = (result.stderr.strip() or result.stdout.strip() or "(无输出)")

        if attempt <= retries:
            delay = retry_base_delay * (2 ** (attempt - 1))  # 8s, 16s, 32s...
            print(
                f"  [重试] {selected} 第 {attempt} 次失败，{delay:.0f}s 后重试：{last_err[:120]}",
                file=sys.stderr, flush=True,
            )
            time.sleep(delay)

    raise TranslatorError(f"{selected} CLI 连续 {retries + 1} 次失败:\n{last_err}")
