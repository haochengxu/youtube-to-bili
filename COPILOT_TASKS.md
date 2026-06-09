# Copilot implementation tasks

This file tracks implementation tasks that are suitable for Copilot or another coding agent. Keep each task scoped, testable, and safe by default. Codex should review and verify changes before any real upload or account-side mutation.

## Recommended order

1. Short-video English subtitle decision.
2. Learning summary output.
3. Bilibili replacement preparation.
4. Multi-platform publishing / Douyin dry-run.

## Task 1: Bilibili replacement preparation

### Goal

For videos that have already been uploaded to Bilibili, prepare the local information needed for a manual replacement workflow. Do not automatically replace or mutate online submissions yet.

### Background

`uploaded/history.json` records previous uploads. Rebuilt videos live in `output/{video_id}.mp4`. Bilibili replacement behavior should be treated as a platform-side manual operation until it is confirmed safely.

### Requirements

- Add `replace_bili_prepare.py`.
- Input: local YouTube video id, for example:

```bash
python3 replace_bili_prepare.py G8DJHg428rQ
```

- Read `uploaded/history.json` and locate the matching record by `video_id`.
- Print a replacement checklist containing:
  - local output video path
  - title
  - description, if available
  - tags, if available
  - original YouTube URL, if available
  - Bilibili `bvid` / `aid`, if available
- If `bvid` / `aid` is missing, print a clear warning that the script cannot identify the Bilibili submission automatically.
- Do not call `biliup`.
- Do not trigger login, upload, delete, replace, or any other online mutation.
- Update `README.md` with a short "replace uploaded Bilibili video" workflow:
  - run `python3 audit_uploaded.py`
  - rebuild the target video
  - run `python3 replace_bili_prepare.py VIDEO_ID`
  - manually edit/replace in Bilibili Creator Center

### Tests

- Add fixture-style tests for:
  - matching history record with `bvid`
  - matching history record without `bvid` / `aid`
  - missing output video
  - missing history record

### Acceptance criteria

- The script is read-only with respect to remote platforms.
- Error messages are actionable.
- It works even when optional history fields are absent.

## Task 2: Short-video English subtitle decision

### Goal

Short vertical videos should hide generated English subtitles when the source video already contains burned-in English captions, but should show English + Chinese when no English captions are detected.

### Background

Some shorts, such as recent Adyashanti videos, already include English hard subtitles. Overlaying generated English text can cover the source subtitle. Other short videos may not have English on screen, so Chinese-only output loses useful learning context.

### Requirements

- Keep `SHOW_ENGLISH` support:
  - `auto`: default
  - `1`, `true`, `yes`: force show English
  - `0`, `false`, `no`: force hide English
- In `auto` mode:
  - horizontal video: show English + Chinese
  - vertical video with detected burned-in subtitles: hide generated English
  - vertical video without detected burned-in subtitles: show English + Chinese
  - vertical video with unknown detection result: show English + Chinese
- Add a lightweight burned-subtitle detector, for example `detect_burned_subtitles.py`:
  - input: video path
  - sample several frames near the bottom of the image
  - use simple image heuristics, not OCR, to return `yes`, `no`, or `unknown`
  - fail open to `unknown`
- Wire the detector into `pipeline.sh`.
- Log the final decision in `pipeline.sh`, including video orientation, detector result, and effective `SHOW_ENGLISH` value.
- Keep `make_ass.py` controllable through explicit environment or argument behavior.

### Tests

Add tests around the decision function:

- vertical + detected `yes` -> hide English
- vertical + detected `no` -> show English
- vertical + detected `unknown` -> show English
- horizontal -> show English
- explicit force show / hide overrides auto

### Acceptance criteria

- A vertical short with existing English captions does not get generated English overlaid.
- A vertical short without existing English captions gets both English and Chinese generated subtitles.
- Detector failure does not remove English subtitles.

## Task 3: Learning summary output

### Goal

Generate a compact learning-oriented Markdown summary for each processed video. Do not publish full subtitle text by default.

### Background

Complete bilingual subtitles are useful as local artifacts, but they are too long for Bilibili descriptions and often less useful than a short study note. The project should keep full subtitles in `subtitles/` and generate separate notes in `summaries/`.

### Requirements

- Add `summarize_subtitles.py`.
- Input: English SRT and Chinese SRT, for example:

```bash
python3 summarize_subtitles.py subtitles/r2q_VN5beLs.en.srt subtitles/r2q_VN5beLs.zh.srt
```

- Output: `summaries/{video_id}.md`.
- Reuse `translator_cli.py` so `TRANSLATOR=codex|copilot|hermes` works consistently.
- Include:
  - video title, when available
  - original YouTube URL, when available
  - 3 to 5 core ideas
  - keyword table with English term, Chinese translation, and short explanation
  - a short Bilibili-friendly description paragraph
  - optional timestamp chapters, grouped roughly every 3 to 8 minutes
- Do not put the full transcript into the summary.
- Add README documentation explaining:
  - full subtitles remain in `subtitles/*.srt` and `subtitles/*.ass`
  - learning summaries live in `summaries/*.md`

### Tests

- Add fixture / dry-run tests that do not call the real LLM.
- Test extraction of `video_id`.
- Test summary file path generation.
- Test that full SRT text is not copied wholesale into the Markdown output.

### Acceptance criteria

- Long videos produce readable study notes instead of huge transcript dumps.
- Summary generation can be tested without network or LLM calls.
- The same backend selection style as translation is preserved.

## Task 4: Multi-platform publishing and Douyin dry-run

### Goal

Add a platform publishing abstraction and prepare Douyin support as a safe dry-run first.

### Background

Bilibili upload exists today. Douyin support has more account, OAuth, API permission, and content-shape constraints, so the first implementation should validate files and print the intended action rather than uploading.

### Requirements

- Add `publishers/`:
  - `publishers/base.py`
  - `publishers/bilibili.py`
  - `publishers/douyin.py`
- Add `publish.py`.
- CLI shape:

```bash
python3 publish.py VIDEO_ID --platform bilibili
python3 publish.py VIDEO_ID --platform douyin --dry-run
```

- `platform=bilibili`:
  - preserve the existing Bilibili upload behavior or print the equivalent existing upload command
  - do not break `bili_upload_v2.py`
- `platform=douyin`:
  - implement dry-run only
  - validate video file exists
  - validate container / extension: `mp4` or `webm`
  - validate size <= 4 GB
  - warn that files over 50 MB should use chunked upload
  - mark files over 300 MB as requiring chunked upload
  - warn when duration is over 15 minutes
  - warn when aspect ratio is not suitable for Douyin vertical publishing
  - print required OAuth/config fields
- Add `config/publishers.example.toml` with placeholders:
  - Bilibili cookie path
  - Douyin `client_key`, `client_secret`, `open_id`, `access_token`
- Do not implement browser automation for Douyin login.
- Do not commit any real token, cookie, or credential.

### Tests

- Test dry-run validation behavior.
- Test missing file.
- Test unsupported extension.
- Test size thresholds.
- Test long-duration warning with a mocked probe result.

### Acceptance criteria

- Bilibili behavior remains compatible with the current workflow.
- Douyin path cannot accidentally upload anything.
- Config is explicit and credential-safe.

## Codex review checklist

Before accepting Copilot changes:

- Run `python3 -m py_compile *.py`.
- Run all project tests.
- Run `bash -n pipeline.sh`.
- Run `python3 audit_uploaded.py`.
- Confirm no script performs remote upload, replacement, deletion, or login unless the user explicitly asked for that run.
- For subtitle display changes, render or sample at least one vertical and one horizontal frame.
- Check `git diff` for accidental credential, media, or generated-output churn.
