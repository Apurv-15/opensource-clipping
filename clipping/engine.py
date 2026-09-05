"""
clipping.engine — Download, Transcription & Gemini AI Analysis

Maps to Cell 2 (The Engine) of the notebook.
"""

import json
import os
import re
import shutil
import time

from yt_dlp import YoutubeDL
from faster_whisper import WhisperModel


# ==============================================================================
# TAHAP 1: DOWNLOAD VIDEO
# ==============================================================================

def _apply_fast_downloader_opts(ydl_opts: dict) -> None:
    """Inject 16-connection aria2c slicing and 8-thread concurrent fragment downloading."""
    ydl_opts["concurrent_fragment_downloads"] = 8
    ydl_opts["http_chunk_size"] = 10485760  # 10 MB chunks to reduce server-side throttling
    ydl_opts["buffersize"] = 1024 * 1024

    aria2c_bin = shutil.which("aria2c") or ("/opt/homebrew/bin/aria2c" if os.path.exists("/opt/homebrew/bin/aria2c") else None)
    if aria2c_bin:
        ydl_opts["external_downloader"] = {"default": aria2c_bin}
        ydl_opts["external_downloader_args"] = {
            "default": [
                "-x", "16",
                "-s", "16",
                "-k", "1M",
                "--max-connection-per-server=16",
                "--min-split-size=1M",
                "--file-allocation=none",
            ]
        }


def _build_ydl_format_selector(download_source_height: str | int) -> str:
    """
    Build a yt-dlp format selector string for source-quality preference.
    """
    # Skip AV1 codec as it lacks HW acceleration on many platforms (e.g., Colab T4)
    # and causes decoding failures in OpenCV/FFmpeg software fallbacks.
    # Note: Using [vcodec!*=av01] to safely ensure it does not contain 'av01' anywhere.
    codec_filter = "[vcodec!*=av01]"

    if download_source_height == "max":
        return f"bestvideo{codec_filter}+bestaudio/best{codec_filter}"

    try:
        h_val = int(download_source_height)
    except (ValueError, TypeError):
        h_val = 0

    if 0 < h_val <= 1080:
        # For standard resolutions, strictly prefer native MP4 (H.264/AAC), ensuring no AV1 in mp4
        return (
            f"bestvideo[height<=?{h_val}][ext=mp4]{codec_filter}+bestaudio[ext=m4a]/"
            f"bestvideo[height<=?{h_val}]{codec_filter}+bestaudio/"
            f"best[height<=?{h_val}][ext=mp4]{codec_filter}/"
            f"best[height<=?{h_val}]{codec_filter}"
        )

    return (
        f"bestvideo[height<=?{download_source_height}]{codec_filter}+bestaudio/"
        f"best[height<=?{download_source_height}]{codec_filter}"
    )


_PLATFORM_LABELS = {
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "gdrive": "Google Drive",
}


def _extract_gdrive_file_id(url: str) -> str | None:
    """Extract the Google Drive file ID from various URL formats."""
    import re as _re
    m = _re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    m = _re.search(r"[?&]id=([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    return None


def _download_gdrive(url: str, output_path: str) -> None:
    """Download a video from Google Drive using gdown (more reliable than yt-dlp)."""
    import gdown

    file_id = _extract_gdrive_file_id(url)
    if not file_id:
        raise RuntimeError(
            f"Unable to extract file ID from Google Drive URL: {url}\n"
            "      Supported formats:\n"
            "        • https://drive.google.com/file/d/FILE_ID/view\n"
            "        • https://drive.google.com/open?id=FILE_ID"
        )

    download_url = f"https://drive.google.com/uc?id={file_id}"
    print(f"      📥 File ID: {file_id}")
    gdown.download(download_url, output_path, quiet=False)


def _ydl_progress_hook(d: dict) -> None:
    """Render single-line download progress bar from yt-dlp hook data."""
    status = d.get("status")
    if status == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        downloaded = d.get("downloaded_bytes", 0)
        speed = d.get("speed")
        eta = d.get("eta")
        spd = f"{speed / 1024 / 1024:4.1f}MB/s" if speed else "  --MB/s"
        eta_s = f"{eta:>3}s" if eta is not None else " --s"
        if total:
            pct = downloaded / total * 100
            filled = int(20 * downloaded / total)
            bar = "█" * filled + " " * (20 - filled)
            print(
                f"\r      Download: {pct:3.0f}%|{bar}| "
                f"{downloaded / 1048576:.0f}/{total / 1048576:.0f}MB {spd} ETA {eta_s}   ",
                end="", flush=True,
            )
        else:
            # Unknown size (live/streamed manifest) — display byte + speed only.
            print(
                f"\r      Download: {downloaded / 1048576:.0f}MB {spd}   ",
                end="", flush=True,
            )
    elif status == "finished":
        print(flush=True)


def download_video(
    url: str,
    output_path: str,
    use_dlp_subs: bool = False,
    download_source_height: str | int = "max",
    source_platform: str = "youtube",
) -> None:
    """
    Download a video to *output_path* with configurable source height.

    Parameters
    ----------
    source_platform : str
        One of ``"youtube"`` (default), ``"tiktok"``, ``"instagram"``,
        or ``"gdrive"``.
    """
    platform_label = _PLATFORM_LABELS.get(source_platform, source_platform)
    uses_youtube_format = source_platform == "youtube"

    if url:
        import re
        url = re.sub(r"^https?:/+", "https://", url.strip())
        if url.startswith("www."):
            url = "https://" + url

    print(f"[1/3] Downloading video from {platform_label}...")
    if download_source_height == "max":
        print("      🎯 Source quality: highest available", flush=True)
    else:
        print(f"      🎯 Source quality: up to {download_source_height}p", flush=True)

    # --- Google Drive: use gdown instead of yt-dlp ---
    if source_platform == "gdrive":
        _download_gdrive(url, output_path)
        if not os.path.exists(output_path):
            raise RuntimeError(
                f"❌ Download from Google Drive failed — file not found at {output_path}"
            )
        print(f"      ✅ Video successfully downloaded from Google Drive.", flush=True)
        return

    # --- Build yt-dlp options per platform ---
    if uses_youtube_format:
        # YouTube: complex format selector + AV1 filter + remote components
        ydl_opts = {
            "format": _build_ydl_format_selector(download_source_height),
            "outtmpl": output_path,
            "quiet": True,
            "merge_output_format": "mp4",
            "remote_components": ["ejs:github"],
            "progress_hooks": [_ydl_progress_hook],
            "extractor_args": {"youtube": ["player_client=android,web"]},
        }
    else:
        # TikTok / Instagram: ensure video and audio are merged
        # We explicitly prefer H.264 over H.265 (TikTok's bytevc1) to prevent 
        # PyAV/faster-whisper from crashing with IndexError on Kaggle/Colab.
        ydl_opts = {
            "format": "bestvideo[vcodec^=h264]+bestaudio/best[vcodec^=h264]/best",
            "outtmpl": output_path,
            "quiet": True,
            "merge_output_format": "mp4",
            "progress_hooks": [_ydl_progress_hook],
        }

    # --- Subtitle download — only supported for YouTube ---
    if use_dlp_subs and uses_youtube_format:
        print("      Searching for automatic subtitles (en / id)...")
        import glob

        for lang in ["en", "en-US", "en-GB", "hi", "id"]:
            ydl_opts_subs = ydl_opts.copy()
            ydl_opts_subs.update({
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitleslangs": [lang],
                "subtitlesformat": "json3",
                "skip_download": True,  # Focus on downloading subtitles only
            })

            try:
                with YoutubeDL(ydl_opts_subs) as ydl:
                    ydl.download([url])

                # Check if json3 for this language was successfully downloaded
                if glob.glob(output_path.replace(".mp4", f".*.json3")):
                    print(f"      ✅ Subtitle '{lang}' found. Proceeding to video...")
                    break
            except Exception as e:
                print(f"      ⚠️ Failed to retrieve subtitle '{lang}' ({e}). Trying next option...")
    elif use_dlp_subs and not uses_youtube_format:
        print(f"      ℹ️ {platform_label} does not provide automatic subtitles. Whisper will be used.")

    # Run video download separately from subtitle handling with multi-thread/aria2c acceleration
    _apply_fast_downloader_opts(ydl_opts)

    with YoutubeDL(ydl_opts) as ydl:
        # Extra step to verify resolution before downloading
        try:
            info = ydl.extract_info(url, download=False)
            best_h = info.get("height", "unknown")
            v_codec = info.get("vcodec", "unknown")
            print(f"      ✅ Downloading: {best_h}p (Codec: {v_codec})", flush=True)
        except Exception as e:
            print(f"      ⚠️ Failed to check detailed info: {e}", flush=True)

        ydl.download([url])

    # --- Post-download verification ---
    if not os.path.exists(output_path):
        raise RuntimeError(
            f"❌ Download from {platform_label} failed — video file not found at {output_path}.\n"
            "      Please make sure the URL is valid and publicly accessible."
        )


# ==============================================================================
# TAHAP 2: TRANSKRIPSI WHISPER & JSON3 FALLBACK
# ==============================================================================

def parse_youtube_json3_subs(json_path: str, max_words_per_subtitle: int = 5) -> tuple[str, list[dict]]:
    """
    Parse downloaded YouTube JSON3 subtitles into transkrip_lengkap and data_segmen.
    Returns empty string/list if parsing fails.
    """
    import json

    print("[2/3] Memproses subtitle JSON3 dari YouTube...")
    transkrip_lengkap = ""
    data_segmen = []

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            subs_data = json.load(f)

        events = subs_data.get("events", [])

        flat_words = []
        for event in events:
            # YouTube timestamps are in ms
            t_start = event.get("tStartMs", 0) / 1000.0
            d_duration = event.get("dDurationMs", 0) / 1000.0
            event_end = t_start + d_duration

            segs = event.get("segs", [])
            for i, seg in enumerate(segs):
                text = seg.get("utf8", "")
                if not text.strip() or text == "\n":
                    continue

                # tOffsetMs is offset from t_start
                offset = seg.get("tOffsetMs", 0) / 1000.0
                seg_start = t_start + offset

                # Determine end of this segment
                if i < len(segs) - 1:
                    next_offset = segs[i + 1].get("tOffsetMs", 0) / 1000.0
                    seg_end = t_start + next_offset
                else:
                    seg_end = event_end

                if seg_end <= seg_start:
                    seg_end = seg_start + 1.0  # Fallback duration

                # Clean up YouTube subtitle artifacts
                clean_text = text.replace("\n", " ").replace("\u200b", "").strip()
                # Remove HTML tags (e.g., <i>, </i>, <b>, </b>, <font color="...">)
                clean_text = re.sub(r"<[^>]+>", "", clean_text)
                # Remove YouTube annotation brackets: [Music], [Applause], [Laughter], etc.
                clean_text = re.sub(r"\[[\w\s]+\]", "", clean_text)
                # Remove speaker change markers: >> 
                clean_text = re.sub(r">>\s*", "", clean_text)
                # Remove music symbols: ♪, ♫, etc.
                clean_text = re.sub(r"[♪♫♬♩]", "", clean_text)
                # Remove leading dashes often used for speaker identification
                clean_text = re.sub(r"^\s*-\s+", "", clean_text)
                # Collapse multiple spaces into one
                clean_text = re.sub(r"\s{2,}", " ", clean_text).strip()

                if clean_text:
                    # Memecah teks menjadi kata tunggal agar karaoke per-kata bekerja seperti whisper
                    words_in_seg = clean_text.split()
                    if not words_in_seg:
                        continue

                    duration_per_word = (seg_end - seg_start) / len(words_in_seg)

                    for w_idx, w_text in enumerate(words_in_seg):
                        w_start = seg_start + (w_idx * duration_per_word)
                        w_end = w_start + duration_per_word

                        flat_words.append({
                            "word": w_text,
                            "start": w_start,
                            "end": w_end,
                        })

        # Adjust end times based on the start time of the next word to prevent overlaps
        for i in range(len(flat_words) - 1):
            if flat_words[i]["end"] > flat_words[i + 1]["start"]:
                flat_words[i]["end"] = max(flat_words[i]["start"] + 0.1, flat_words[i + 1]["start"])

        # Group them into segments
        chunk_words = []
        chunk_start = 0.0

        for i, w in enumerate(flat_words):
            if len(chunk_words) == 0:
                chunk_start = w["start"]

            chunk_words.append(w)

            if len(chunk_words) == max_words_per_subtitle or i == len(flat_words) - 1:
                chunk_text = " ".join([cw["word"] for cw in chunk_words])
                chunk_end = w["end"]
                transkrip_lengkap += f"[{chunk_start:.1f} - {chunk_end:.1f}] {chunk_text}\n"

                data_segmen.append({
                    "start": chunk_start,
                    "end": chunk_end,
                    "words": chunk_words,
                })
                chunk_words = []

        return transkrip_lengkap, data_segmen

    except Exception as e:
        print(f"⚠️ Failed to parse JSON3: {e}")
        return "", []


def transcribe_video(
    video_path: str,
    max_words_per_subtitle: int = 5,
    model_size: str = "large-v3",
    device: str = "cuda",
    compute_type: str = "float16",
) -> tuple[str, list[dict]]:
    """
    Transcribe *video_path* using Faster-Whisper.

    Returns
    -------
    transkrip_lengkap : str
        Human-readable transcript with timestamps.
    data_segmen : list[dict]
        Word-level segments grouped by *max_words_per_subtitle*.
    """
    print("[2/3] Starting transcription with Faster-Whisper (Word-Level)...")

    # These steps run without output inside faster-whisper before the first
    # segment is produced, so we announce each phase to avoid looking hung.
    print(
        f"      ⏳ Loading Whisper model '{model_size}' ({device})"
        " — first download may take time...",
        flush=True,
    )
    try:
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception as e:
        err_str = str(e).lower()
        if "float16" in err_str or "float 16" in err_str:
            print(f"      ℹ️ Device/CPU does not support float16 ({e}). Switching automatically to int8...", flush=True)
            model = WhisperModel(model_size, device="cpu", compute_type="int8")
        elif device == "cuda" or "cuda" in err_str:
            print(f"      ⚠️ CUDA not available on this system ({e}). Switching automatically to CPU (int8)...", flush=True)
            model = WhisperModel(model_size, device="cpu", compute_type="int8")
        else:
            print(f"      ⚠️ Whisper failed with compute_type={compute_type} ({e}). Trying CPU fallback (int8)...", flush=True)
            try:
                model = WhisperModel(model_size, device="cpu", compute_type="int8")
            except Exception:
                raise e

    print("      ⏳ Decoding audio & extracting features...", flush=True)
    segments, info = model.transcribe(video_path, beam_size=5, word_timestamps=True)

    transkrip_lengkap = ""
    data_segmen: list[dict] = []

    # Audio timestamp based progress bar
    from tqdm import tqdm

    total_dur = round(info.duration, 2)
    progress = tqdm(
        total=total_dur,
        unit="s",
        desc="      Transcription",
        bar_format="{desc}: {percentage:3.0f}%|{bar}| {n:.0f}/{total:.0f}s [{elapsed}<{remaining}]",
    )

    for segment in segments:
        # Clamp agar floating-point drift melewati durasi tidak overshoot.
        progress.update(min(segment.end, total_dur) - progress.n)
        transkrip_lengkap += f"[{segment.start:.1f} - {segment.end:.1f}] {segment.text}\n"

        if segment.words:
            chunk_words: list[dict] = []
            chunk_start = 0.0

            for i, w in enumerate(segment.words):
                if len(chunk_words) == 0:
                    chunk_start = w.start

                chunk_words.append({
                    "word": w.word.strip(),
                    "start": w.start,
                    "end": w.end,
                })

                if len(chunk_words) == max_words_per_subtitle or i == len(segment.words) - 1:
                    data_segmen.append({
                        "start": chunk_start,
                        "end": w.end,
                        "words": chunk_words,
                    })
                    chunk_words = []

    progress.update(total_dur - progress.n)  # snap ke 100% saat selesai
    progress.close()
    return transkrip_lengkap, data_segmen


# ==============================================================================
# TAHAP 3: ANALISIS GEMINI AI
# ==============================================================================

TARGET_ACCOUNTS = {
    "Business": {
        "akun_tujuan": "Business.Mereska",
        "angle_desc": "If the angle focuses on business, brand building, revenue, commerce, sales, founders, marketing, or SMEs.",
        "bio": "Business insights, founder stories & market strategies. Business | Founder | Finance | Growth | Marketing"
    },
    "Life": {
        "akun_tujuan": "Life.Mereska",
        "angle_desc": "If the angle focuses on personal life, lifestyle, career, mindset, relationships, personal finance, or self growth.",
        "bio": "Curated insights to upgrade your life & mindset. Podcast | Career | Finance | Mindset | Self Growth"
    },
    "Creator": {
        "akun_tujuan": "Creator.Mereska",
        "angle_desc": "If the angle focuses on digital content creation, AI, affiliate marketing, software tools, clipping, or monetizing online.",
        "bio": "Exploring digital content & creator tools to monetize. AI | Affiliate | Clips | Tools | Monetize"
    },
    "Muslim": {
        "akun_tujuan": "Muslim.Mereska",
        "angle_desc": "If the angle focuses on faith, spirituality, purpose, ethical work, Islamic values, family, or mindful living.",
        "bio": "Daily mindfulness, purpose & faith-driven values. Spiritual | Family | Purpose | Ethics"
    }
}

def _build_account_classification_prompt() -> str:
    lines = []
    for tipe, data in TARGET_ACCOUNTS.items():
        lines.append(f"- {tipe}: {data['angle_desc']}")
        lines.append(f"  (akun_tujuan: \"{data['akun_tujuan']}\", bio: \"{data['bio']}\")")
    return "\n".join(lines)


# ---- Retry Config ----
MAX_ATTEMPTS = 3
INITIAL_WAIT_SECONDS = 5
WAIT_INCREMENT_SECONDS = 5
REQUEST_TIMEOUT_MS = 120_000  # 2 minutes timeout for responsive feedback
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def _extract_status_code(exc: Exception):
    for attr in ("status_code", "code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)

    match = re.search(r"\b(400|401|402|403|404|408|429|500|502|503|504)\b", str(exc))
    return int(match.group(1)) if match else None


def diagnose_ai_error(exc: Exception, provider: str, model: str) -> tuple[int | None, str, str]:
    """
    Returns (status_code, error_summary, resolution_hint).
    """
    code = _extract_status_code(exc)
    msg = str(exc)

    if code == 402 or "PAYMENT_METHOD_REQUIRED" in msg or "billing" in msg.lower():
        return (402, "Billing/Payment required", f"Add payment method at provider console or switch provider to Gemini.")

    if code == 404 or "NOT_FOUND" in msg or "no longer available" in msg.lower():
        return (404, "Model retired or not found", f"Model '{model}' is unavailable. Switch to an active model (e.g. gemini-3-flash-preview or gemini-flash-latest).")

    if code == 429 or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower() or "rate" in msg.lower():
        return (429, "Rate limit / Quota exceeded", f"API rate limit reached for {model}. Backing off automatically before retry.")

    if code in (408, 504) or "timeout" in msg.lower() or "deadline" in msg.lower():
        return (code or 408, "Request timed out", f"Call to {model} took too long (>120s). Retrying with backoff or fallback.")

    if code in (500, 502, 503) or "temporarily unavailable" in msg.lower() or "overloaded" in msg.lower():
        return (code or 503, f"{provider.capitalize()} overloaded", f"Provider service temporarily overloaded. Backing off automatically.")

    if code in (400, 401, 403) or "API_KEY_INVALID" in msg or "invalid" in msg.lower():
        return (code, "Authentication / API key error", f"Verify your {provider.upper()}_API_KEY in .env or Settings.")

    return (code, f"{type(exc).__name__}: {msg[:100]}", "Check API keys, network connection, or switch AI models.")


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, json.JSONDecodeError):
        return True

    code = _extract_status_code(exc)
    if code in RETRYABLE_STATUS_CODES:
        return True

    msg = str(exc).lower()
    keywords = (
        "timeout", "temporarily unavailable", "deadline",
        "connection reset", "connection aborted", "service unavailable",
        "resource_exhausted", "quota",
    )
    return any(k in msg for k in keywords)


def _generate_json_with_retry(client, model, fallback_model, contents, config, logger_callback=None):
    last_exc = None
    status_code = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            start_time = time.time()
            msg = f"Calling Gemini model '{model}' (Attempt {attempt}/{MAX_ATTEMPTS})..."
            print(f"[Gemini] {msg}", flush=True)
            if logger_callback:
                logger_callback(
                    msg,
                    level="ai",
                    ai_status={
                        "provider": "gemini",
                        "model": model,
                        "status": "querying",
                        "attempt": attempt,
                        "max_attempts": MAX_ATTEMPTS,
                        "fallback_model": fallback_model,
                        "last_error": None,
                        "last_status_code": None,
                        "retry_in_seconds": 0,
                    },
                )

            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )

            text = getattr(response, "text", None)
            if not text or not text.strip():
                raise ValueError("Gemini returned empty response.text.")

            data = json.loads(text)
            elapsed = time.time() - start_time
            clip_count = len(data) if isinstance(data, list) else 1
            success_msg = f"Gemini ({model}) responded successfully in {elapsed:.1f}s ({clip_count} viral clips identified)."
            print(f"[Gemini] ✅ {success_msg}", flush=True)
            if logger_callback:
                logger_callback(
                    success_msg,
                    level="ai_success",
                    ai_status={
                        "provider": "gemini",
                        "model": model,
                        "status": "success",
                        "attempt": attempt,
                        "max_attempts": MAX_ATTEMPTS,
                        "elapsed_seconds": round(elapsed, 2),
                        "clips_found": clip_count,
                        "last_error": None,
                    },
                )
            return data

        except Exception as exc:
            last_exc = exc
            code, summary, hint = diagnose_ai_error(exc, "gemini", model)
            status_code = code
            retryable = _is_retryable(exc)

            warn_msg = f"Gemini Attempt {attempt}/{MAX_ATTEMPTS} failed | [{code or 'ERR'}] {summary} | {str(exc)[:140]}"
            print(f"[Gemini] ⚠️ {warn_msg}", flush=True)

            if (not retryable) or attempt == MAX_ATTEMPTS:
                if logger_callback:
                    logger_callback(
                        warn_msg,
                        level="ai_error" if not fallback_model else "ai_degraded",
                        ai_status={
                            "provider": "gemini",
                            "model": model,
                            "status": "degraded" if fallback_model else "failed",
                            "attempt": attempt,
                            "max_attempts": MAX_ATTEMPTS,
                            "last_error": str(exc),
                            "last_status_code": code,
                            "resolution_hint": hint,
                        },
                    )
                break

            wait_seconds = INITIAL_WAIT_SECONDS + ((attempt - 1) * WAIT_INCREMENT_SECONDS)
            retry_msg = f"Retrying in {wait_seconds}s (Attempt {attempt + 1}/{MAX_ATTEMPTS})... Hint: {hint}"
            print(f"[Gemini] ⏳ {retry_msg}", flush=True)
            if logger_callback:
                logger_callback(
                    f"{warn_msg} — {retry_msg}",
                    level="ai_retry",
                    ai_status={
                        "provider": "gemini",
                        "model": model,
                        "status": "retrying",
                        "attempt": attempt,
                        "max_attempts": MAX_ATTEMPTS,
                        "last_error": str(exc),
                        "last_status_code": code,
                        "retry_in_seconds": wait_seconds,
                        "resolution_hint": hint,
                    },
                )
            time.sleep(wait_seconds)

    print(f"[Gemini] Primary model ({model}) attempt failed.", flush=True)
    if fallback_model:
        fallback_msg = f"Primary model ({model}) failed. Engaging fallback model ({fallback_model})..."
        print(f"[Gemini] 🔄 {fallback_msg}", flush=True)
        if logger_callback:
            logger_callback(
                fallback_msg,
                level="ai_fallback",
                ai_status={
                    "provider": "gemini",
                    "model": fallback_model,
                    "status": "fallback",
                    "attempt": 1,
                    "max_attempts": 1,
                    "last_error": str(last_exc),
                    "last_status_code": status_code,
                    "resolution_hint": f"Primary model failed. Attempting fallback {fallback_model}.",
                },
            )
        try:
            start_fb = time.time()
            response = client.models.generate_content(
                model=fallback_model,
                contents=contents,
                config=config,
            )
            text = getattr(response, "text", None)
            if not text or not text.strip():
                raise ValueError("Gemini fallback returned empty response.text.")

            data = json.loads(text)
            elapsed_fb = time.time() - start_fb
            clip_count = len(data) if isinstance(data, list) else 1
            success_fb_msg = f"Gemini Fallback ({fallback_model}) succeeded in {elapsed_fb:.1f}s ({clip_count} clips identified)."
            print(f"[Gemini] ✅ {success_fb_msg}", flush=True)
            if logger_callback:
                logger_callback(
                    success_fb_msg,
                    level="ai_success",
                    ai_status={
                        "provider": "gemini",
                        "model": fallback_model,
                        "status": "success",
                        "elapsed_seconds": round(elapsed_fb, 2),
                        "clips_found": clip_count,
                    },
                )
            return data
        except Exception as exc_fallback:
            code_fb, sum_fb, hint_fb = diagnose_ai_error(exc_fallback, "gemini", fallback_model)
            fail_fb_msg = f"Gemini Fallback ({fallback_model}) failed | [{code_fb or 'ERR'}] {sum_fb}: {exc_fallback}"
            print(f"[Gemini] ❌ {fail_fb_msg}", flush=True)
            if logger_callback:
                logger_callback(
                    fail_fb_msg,
                    level="ai_error",
                    ai_status={
                        "provider": "gemini",
                        "model": fallback_model,
                        "status": "failed",
                        "last_error": str(exc_fallback),
                        "last_status_code": code_fb,
                        "resolution_hint": hint_fb,
                    },
                )
            raise RuntimeError(
                f"Failed to call primary & fallback Gemini. "
                f"Primary Report status={status_code}, error={last_exc} | "
                f"Fallback Report error={exc_fallback}"
            ) from exc_fallback

    raise RuntimeError(
        f"Failed to call Gemini after {MAX_ATTEMPTS} attempts. Last error: {last_exc}"
    ) from last_exc


# ==== KONFIGURASI DURASI KLIP ====
# Ubah nilai di bawah ini jika ingin mengganti batas durasi klip (dalam detik)
MIN_CLIP_DURATION = int(os.environ.get("DEFAULT_MIN_CLIP_DURATION", "20"))
MAX_CLIP_DURATION = int(os.environ.get("DEFAULT_MAX_CLIP_DURATION", "90"))

def get_analysis_prompt(transkrip_lengkap: str, jumlah_clip: int, durasi_hook: int, cfg=None) -> str:
    """Centralized prompt for Gemini, SambaNova, and NVIDIA providers."""
    # Build optional Hook V2 prompt section
    _hook_v2_prompt = ""
    if cfg and getattr(cfg, "hook_v2", False):
        _hook_v2_items = getattr(cfg, "hook_v2_items", 3)
        _hook_v2_style = getattr(cfg, "hook_v2_style", "controversial_fast_glitch")
        _hook_v2_prompt = f"""

HOOK V2 (MULTI-HOOK INTRO — MANDATORY):
- In addition to the standard hook, create "hook_v2" containing {_hook_v2_items} short snippets (0.5-2 seconds) taken from the most striking/controversial/emotional moments within the clip.
- Style: {_hook_v2_style}
- Each item must contain: start_time, end_time, and text (short on-screen punchy text 2-5 words).
- Items must be ordered from strongest to weakest.
- Transitions between items will be added automatically (white flash / glitch).
- Populate the "hook_v2" field as an object with:
  - "enabled": true
  - "items": array of objects (start_time, end_time, text)
  - "transition": object with "type" ("white_flash" or "glitch")
"""

    # Build optional Segment Trimming prompt section
    _segment_prompt = ""
    if cfg and not getattr(cfg, "no_segment_trim", False):
        _silence_hint = ""
        if cfg and getattr(cfg, "silence_trim", False):
            _silence_hint = "\n- AGGRESSIVELY remove dead air / silence / pauses longer than 0.5s."
        _segment_prompt = f"""

SEGMENT-BASED TRIMMING (KEEP SEGMENTS — MANDATORY):
- For each clip, analyze whether there are filler, silent, rambling, or dull portions in the middle.
- If found, split the clip into "keep_segments" — preserving only the highest value parts.
- Each segment contains: start_time and end_time.
- Segments must be chronological and strictly non-overlapping.
- If the entire clip is already dense and engaging, create 1 segment covering the whole duration.{_silence_hint}
- Populate the "keep_segments" field as an array of objects (start_time, end_time).
"""
    target_lang = getattr(cfg, "target_language", "english").lower()
    if target_lang == "hinglish":
        lang_instruction = """
LANGUAGE & AUDIENCE INSTRUCTION:
- Target Language: HINGLISH (Hindi written entirely in English / Roman alphabet letters).
- Example: "aaj kab aane wala hai", "yeh video dekhna zaroori hai", "sabse zyada viral scene".
- STRICT RULE: Do NOT use Hindi/Devanagari script characters (no देवनागरी). Write all words, keywords, titles, and typography plans in natural English/Latin letters.
"""
    elif target_lang == "indonesian":
        lang_instruction = """
LANGUAGE & AUDIENCE INSTRUCTION:
- Target Language: INDONESIAN (Bahasa Indonesia).
- Generate titles, summaries, hooks, hashtags, and metadata in natural Indonesian.
"""
    else:
        lang_instruction = f"""
LANGUAGE & AUDIENCE INSTRUCTION:
- Target Language: {target_lang.upper()} (Natural English).
- All titles, summaries, hooks, hashtags, on-screen text, and metadata MUST be generated in clear, compelling, professional English.
"""

    min_clip_dur = int(getattr(cfg, "min_clip_duration", None) or MIN_CLIP_DURATION)
    max_clip_dur = int(getattr(cfg, "max_clip_duration", None) or MAX_CLIP_DURATION)

    return f"""
You are an expert Art Director, Short-Form Video Editor, and Viral Growth Strategist for TikTok, Instagram Reels, and YouTube Shorts.
{lang_instruction}
Read the following video transcript. Transcript format:
[start_seconds - end_seconds] text

PRIMARY TASK:
- Identify {jumlah_clip} of the most engaging, powerful, shareable, and viral moments from this video to produce short-form clips.
- Sort clips from highest viral_score (most likely to go viral) to lowest. The "rank" field represents the position (1, 2, 3...).
- For each clip, provide precise timing, hook, kinetic typography plan, B-roll plan, selection reasoning, cross-platform metadata, and account classification.
- All outputs must be strictly relevant to the specific clip's content, not general video summaries.

CLIP SELECTION & VIRALITY RULES:
- Duration of every clip MUST strictly fall within {min_clip_dur}-{max_clip_dur} seconds (Target Optimal Short-Form Duration).
  FOCUS on concise, fast-paced, high-impact segments to maximize audience retention and completion rates for TikTok/Reels/Shorts algorithms.
- Choose moments with strong emotion, conflict, surprise, unique insight, bold opinions, practical takeaways, or clear punchlines.
- Evaluate virality potential and assign a "viral_score" (1-100):
  - 90-100: Exceptional viral / FYP potential, massive emotional hook, unforgettable statement.
  - 80-89: Very strong, engaging story arc, high retention.
  - 70-79: Solid informative or entertaining segment.
- Prioritize segments that make sense and captivate viewers even without watching the full video.
- Avoid repetitive clips or segments that rehash the same point.
- Avoid flat, rambling, or slow segments that lack a satisfying payoff.

AUDIENCE RETENTION & HOOK RULES:
- The first 3 seconds MUST have an irresistible hook: conflict, curiosity gap, sharp statement, strong emotion, or implicit question.
- Ideal clip narrative structure:
  hook -> quick context -> tension/insight -> payoff.
- Do not pick clips that take too long to get interesting.
- Cut dead air, pleasantries, slow introductions, or irrelevant tangents.
- Aim for clips that make viewers stop scrolling, watch until the end, leave comments, share with friends, or save.

TIMING PRECISION:
- start_time must begin right as the punchy statement or hook begins, not long before.
- end_time must conclude cleanly right after the main punchline, insight, or emotional beat finishes.
- Never cut off words mid-sentence.
- If two strong moments are adjacent and mutually reinforcing, combine them provided total duration stays within {min_clip_dur}-{max_clip_dur} seconds.

INTERNAL VIRAL_SCORE COMPONENTS (1-100):
- Hook strength: 1-20 (how effectively first 3 seconds stop scrolling)
- Emotional intensity: 1-20 (relatability, humor, tension, surprise, inspiration)
- Shareability & comment drive: 1-20 (likelihood of viewers tagging friends or debating)
- Standalone clarity: 1-20 (comprehensible without external context)
- Payoff & completion reward: 1-20 (satisfying conclusion, punchline, or insight)

HOOK (MANDATORY):
- Extract 1 punchiest sentence from INSIDE the clip.
- Must grab immediate attention within ~{durasi_hook} seconds.
- Save as hook_start_time and hook_end_time.
- Must be natural and verbatim from the transcript (no fake clickbait).

KINETIC TYPOGRAPHY PLAN:
- Pick 3-6 SINGLE words with the most weight, emotion, or punch from each clip.
- For each word, specify:
  1. 'kata_utama': the exact single word (exact spelling as spoken).
  2. 'scale_level': 1 (normal), 2 (emphasized/large), or 3 (giant/critical climax).
  3. 'style': "utama" (primary accent color) or "khusus" (contrasting highlight).
  4. 'animasi': "bounce_pop" or "stagger_up".
- Single words only, not long phrases.

B-ROLL STOCK FOOTAGE PLAN:
- Identify 1-3 moments in the clip ideal for stock B-roll overlay footage (3-7s duration each).
- Provide start_time, end_time, and search_query (in concise English, e.g. "person typing laptop fast", "city skyline drone").
- If no B-roll is needed, return empty array [].

BACKGROUND MUSIC (BGM MOOD):
- Select exactly ONE mood from: [chill, epic, sad, upbeat, suspense].

SLOW CLOSING PADDING:
- end_time should include +0.10s to +0.85s padding after the last word so speech does not cut abruptly.

SELECTION REASONING:
- Field 'alasan': explain why this clip was selected, its viral trigger, retention hook, and expected audience reaction.

CROSS-PLATFORM METADATA:
- title_inggris: Punchy, high-CTR English title (max 100 characters).
- title_indonesia: English title (or localized title) for fallback compatibility.
- hastag: 2-3 relevant hashtags separated by spaces (e.g. "#mindset #productivity #career").
- description_hook: Exactly 1 compelling opening sentence in English.
- description_context: Exactly 1 clear sentence providing quick context in English.
- keyword_tags: 5-8 relevant search tags in English.
- tiktok_caption: 1-2 conversational sentences optimized for short-form video feeds in English.

OUTPUT FORMAT:
- Output MUST be valid JSON array strictly matching the structure below.
- Do NOT output any markdown, explanations, or text outside the JSON array.
{_hook_v2_prompt}{_segment_prompt}

MANDATORY JSON STRUCTURE:
[
  {{
    "rank": 1,
    "viral_score": 95,
    "start_time": 30.5,
    "end_time": 90.0,
    "hook_start_time": 30.5,
    "hook_end_time": 35.0,
    "bgm_mood": "upbeat",
    "typography_plan": [{{ "kata_utama": "WORD", "scale_level": 2, "style": "utama", "animasi": "bounce_pop" }}],
    "broll_list": [{{ "start_time": 40.0, "end_time": 45.0, "search_query": "laptop work" }}],
    "recommended_visual_broll_hook": [
      {{ "broll_idea": "...", "search_keyword": "...", "why_it_works": "..." }}
    ],
    "hook_v2": {{
      "enabled": true,
      "items": [{{ "start_time": 31.0, "end_time": 32.5, "text": "KEY PHRASE" }}],
      "transition": {{ "type": "white_flash" }}
    }},
    "keep_segments": [
      {{ "start_time": 30.5, "end_time": 55.0 }},
      {{ "start_time": 58.0, "end_time": 90.0 }}
    ],
    "title_inggris": "How to Build Unstoppable Focus",
    "title_indonesia": "How to Build Unstoppable Focus",
    "hastag": "#focus #productivity #success",
    "description_hook": "This single realization will completely change how you approach your daily work.",
    "description_context": "Deep dive into mental clarity and discipline strategies.",
    "keyword_tags": ["productivity", "focus", "discipline", "mindset", "success"],
    "tiktok_caption": "Stop letting distractions dictate your future. Save this reminder for later!",
    "alasan": "Powerful hook in the first 3 seconds, relatable struggle, and an actionable payoff at the end."
  }}
]

Transcript:
{transkrip_lengkap}
"""


def analyze_with_nvidia(transkrip_lengkap: str, cfg, logger_callback=None) -> list[dict]:
    """Analyze transcript using NVIDIA NIM API (OpenAI compatible)."""
    from openai import OpenAI
    
    model = cfg.nvidia_model
    msg = f"Analyzing Top {cfg.jumlah_clip} moments using NVIDIA ({model})..."
    print(f"[3/3] {msg}", flush=True)
    if logger_callback:
        logger_callback(
            f"Calling NVIDIA model '{model}'...",
            level="ai",
            ai_status={
                "provider": "nvidia",
                "model": model,
                "status": "querying",
                "attempt": 1,
                "max_attempts": 1,
            }
        )
    
    if not cfg.api_key_nvidia:
        raise ValueError("NVIDIA_API_KEY not found in environment.")

    client = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=cfg.api_key_nvidia
    )
    
    prompt = get_analysis_prompt(transkrip_lengkap, cfg.jumlah_clip, cfg.durasi_hook, cfg=cfg)
    
    # Define the strict schema for Guided JSON (NVIDIA NIM specific)
    clips_schema = {
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "rank": {"type": "integer"},
                "viral_score": {"type": "integer"},
                "start_time": {"type": "number"},
                "end_time": {"type": "number"},
                "hook_start_time": {"type": "number"},
                "hook_end_time": {"type": "number"},
                "bgm_mood": {
                    "type": "string",
                    "enum": ["chill", "epic", "sad", "upbeat", "suspense"]
                },
                "typography_plan": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "kata_utama": {"type": "string"},
                            "scale_level": {"type": "integer", "enum": [1, 2, 3]},
                            "style": {"type": "string", "enum": ["utama", "khusus"]},
                            "animasi": {"type": "string", "enum": ["bounce_pop", "stagger_up"]}
                        },
                        "required": ["kata_utama", "scale_level", "style", "animasi"]
                    }
                },
                "broll_list": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "start_time": {"type": "number"},
                            "end_time": {"type": "number"},
                            "search_query": {"type": "string"}
                        },
                        "required": ["start_time", "end_time", "search_query"]
                    }
                },
                "recommended_visual_broll_hook": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "broll_idea": {"type": "string"},
                            "search_keyword": {"type": "string"},
                            "why_it_works": {"type": "string"}
                        },
                        "required": ["broll_idea", "search_keyword", "why_it_works"]
                    }
                },
                "title_indonesia": {"type": "string"},
                "title_inggris": {"type": "string"},
                "hastag": {"type": "string"},
                "description_hook": {"type": "string"},
                "description_context": {"type": "string"},
                "keyword_tags": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "tiktok_title_id": {"type": "string"},
                "tiktok_caption_id": {"type": "string"},
                "tiktok_caption": {"type": "string"},
                "alasan": {"type": "string"},
                "klasifikasi_akun": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "tipe_akun": {"type": "string", "enum": list(TARGET_ACCOUNTS.keys())},
                        "akun_tujuan": {"type": "string"},
                        "confidence": {"type": "integer"},
                        "angle_utama": {"type": "string"},
                        "alasan": {"type": "string"},
                        "kata_kunci_pendukung": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "bio_akun": {"type": "string"},
                        "alternatif_akun": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "tipe_akun": {"type": "string", "enum": list(TARGET_ACCOUNTS.keys())},
                                "akun_tujuan": {"type": "string"},
                                "alasan": {"type": "string"}
                            },
                            "required": ["tipe_akun", "akun_tujuan", "alasan"]
                        }
                    },
                    "required": ["tipe_akun", "akun_tujuan", "confidence", "angle_utama", "alasan", "kata_kunci_pendukung", "bio_akun", "alternatif_akun"]
                },
                "hook_v2": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "enabled": {"type": "boolean"},
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "start_time": {"type": "number"},
                                    "end_time": {"type": "number"},
                                    "text": {"type": "string"},
                                },
                                "required": ["start_time", "end_time", "text"],
                            },
                        },
                        "transition": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "type": {"type": "string", "enum": ["white_flash", "glitch"]},
                            },
                            "required": ["type"],
                        },
                    },
                    "required": ["enabled", "items", "transition"],
                },
                "keep_segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "start_time": {"type": "number"},
                            "end_time": {"type": "number"},
                        },
                        "required": ["start_time", "end_time"],
                    },
                },
            },
            "required": [
                "rank", "viral_score", "start_time", "end_time", "hook_start_time", "hook_end_time",
                "bgm_mood", "typography_plan", "broll_list", "recommended_visual_broll_hook", "title_indonesia",
                "title_inggris", "hastag", "description_hook", "description_context",
                "keyword_tags", "tiktok_title_id", "tiktok_caption_id", "tiktok_caption",
                "alasan", "klasifikasi_akun", "hook_v2", "keep_segments"
            ]
        }
    }

    completion = client.chat.completions.create(
        model=cfg.nvidia_model,
        messages=[
            {"role": "system", "content": "You are a professional video editor and strategist. Return JSON only. Follow the provided JSON schema exactly."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.5,
        top_p=1,
        max_tokens=16384,
        extra_body={
            "chat_template_kwargs": {"thinking": False},
            "nvext": {
                "guided_json": clips_schema
            }
        }
    )
    
    content = completion.choices[0].message.content
    
    if "```" in content:
        content = re.sub(r"```(json)?", "", content).strip()
        content = content.split("```")[0].strip()
        
    hasil = json.loads(content)
    
    # Guided JSON should return an array directly if schema says type: array
    # but we keep the unwrapper just in case of non-conforming fallbacks
    if isinstance(hasil, dict):
        for key in ["clips", "data", "highlights"]:
            if key in hasil and isinstance(hasil[key], list):
                hasil = hasil[key]
                break
                
    if not isinstance(hasil, list):
        if isinstance(hasil, dict):
            return [hasil]
        raise ValueError(f"NVIDIA provider returned non-list/dict format: {type(hasil)}")
        
    return hasil


def analyze_with_sambanova(transkrip_lengkap: str, cfg, logger_callback=None) -> list[dict]:
    """Analyze transcript using SambaNova Cloud API (OpenAI compatible)."""
    from openai import OpenAI
    
    model = getattr(cfg, "sambanova_model", "Meta-Llama-3.3-70B-Instruct")
    msg = f"Analyzing Top {cfg.jumlah_clip} moments using SambaNova ({model})..."
    print(f"[3/3] {msg}", flush=True)
    if logger_callback:
        logger_callback(
            f"Calling SambaNova model '{model}'...",
            level="ai",
            ai_status={
                "provider": "sambanova",
                "model": model,
                "status": "querying",
                "attempt": 1,
                "max_attempts": 1,
            }
        )
    
    if not getattr(cfg, "api_key_sambanova", None):
        raise ValueError("SAMBANOVA_API_KEY not found in environment.")

    client = OpenAI(
        base_url="https://api.sambanova.ai/v1",
        api_key=cfg.api_key_sambanova
    )
    
    prompt = get_analysis_prompt(transkrip_lengkap, cfg.jumlah_clip, cfg.durasi_hook, cfg=cfg)
    
    system_msg = (
        "You are a professional video editor and strategist. "
        "You MUST output valid, parseable raw JSON only. "
        "Return a JSON array containing objects corresponding to each clip. "
        "Do NOT include conversational text, markdown explanations, or reasoning."
    )
    
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        top_p=0.9,
        max_tokens=8192,
    )
    
    content = completion.choices[0].message.content or ""
    
    if "```" in content:
        content = re.sub(r"```(json)?", "", content).strip()
        content = content.split("```")[0].strip()
        
    hasil = json.loads(content)
    
    if isinstance(hasil, dict):
        for key in ["clips", "data", "highlights", "moments"]:
            if key in hasil and isinstance(hasil[key], list):
                hasil = hasil[key]
                break
                
    if not isinstance(hasil, list):
        if isinstance(hasil, dict):
            hasil = [hasil]
        else:
            raise ValueError(f"SambaNova provider returned non-list/dict format: {type(hasil)}")
        
    if logger_callback:
        logger_callback(
            f"SambaNova ({model}) responded successfully ({len(hasil)} clips identified).",
            level="ai_success",
            ai_status={
                "provider": "sambanova",
                "model": model,
                "status": "success",
                "clips_found": len(hasil),
            }
        )
    return hasil


def analyze_with_ai(transkrip_lengkap: str, cfg, logger_callback=None) -> list[dict]:
    """Dispatcher for AI analysis based on provider with failure & degradation tracking."""
    provider = getattr(cfg, "ai_provider", "gemini")
    
    if provider == "sambanova":
        model = getattr(cfg, "sambanova_model", "Meta-Llama-3.3-70B-Instruct")
        if not getattr(cfg, "api_key_sambanova", None):
            warn_msg = "SAMBANOVA_API_KEY not found! Automatically falling back to Gemini..."
            print(f"⚠️ {warn_msg}", flush=True)
            if logger_callback:
                logger_callback(
                    warn_msg,
                    level="ai_fallback",
                    ai_status={
                        "provider": "sambanova",
                        "model": model,
                        "status": "fallback",
                        "fallback_model": getattr(cfg, "gemini_model", "gemini-3.6-flash"),
                        "last_error": "Missing SAMBANOVA_API_KEY",
                        "resolution_hint": "Provide a SAMBANOVA_API_KEY in .env/Settings, or keep using Gemini.",
                    }
                )
        else:
            try:
                return analyze_with_sambanova(transkrip_lengkap, cfg, logger_callback=logger_callback)
            except Exception as e:
                code, summary, hint = diagnose_ai_error(e, "sambanova", model)
                warn_msg = f"SambaNova ({model}) failed: [{code or 'ERR'}] {summary}. Automatically falling back to Gemini..."
                print(f"⚠️ {warn_msg}", flush=True)
                if logger_callback:
                    logger_callback(
                        warn_msg,
                        level="ai_fallback",
                        ai_status={
                            "provider": "sambanova",
                            "model": model,
                            "status": "fallback",
                            "fallback_model": getattr(cfg, "gemini_model", "gemini-3.6-flash"),
                            "last_error": str(e),
                            "last_status_code": code,
                            "resolution_hint": hint,
                        }
                    )

    elif provider == "nvidia":
        model = getattr(cfg, "nvidia_model", "deepseek-ai/deepseek-v4-pro")
        if not cfg.api_key_nvidia:
            warn_msg = "NVIDIA_API_KEY not found! Automatically falling back to Gemini..."
            print(f"⚠️ {warn_msg}", flush=True)
            if logger_callback:
                logger_callback(
                    warn_msg,
                    level="ai_fallback",
                    ai_status={
                        "provider": "nvidia",
                        "model": model,
                        "status": "fallback",
                        "fallback_model": getattr(cfg, "gemini_model", "gemini-3.6-flash"),
                        "last_error": "Missing NVIDIA_API_KEY",
                        "resolution_hint": "Provide an NVIDIA_API_KEY in .env/Settings, or keep using Gemini.",
                    }
                )
        else:
            try:
                return analyze_with_nvidia(transkrip_lengkap, cfg, logger_callback=logger_callback)
            except Exception as e:
                code, summary, hint = diagnose_ai_error(e, "nvidia", model)
                warn_msg = f"NVIDIA ({model}) failed: [{code or 'ERR'}] {summary}. Automatically falling back to Gemini..."
                print(f"⚠️ {warn_msg}", flush=True)
                if logger_callback:
                    logger_callback(
                        warn_msg,
                        level="ai_fallback",
                        ai_status={
                            "provider": "nvidia",
                            "model": model,
                            "status": "fallback",
                            "fallback_model": getattr(cfg, "gemini_model", "gemini-3.6-flash"),
                            "last_error": str(e),
                            "last_status_code": code,
                            "resolution_hint": hint,
                        }
                    )
    
    return analyze_with_gemini(transkrip_lengkap, cfg, logger_callback=logger_callback)


def analyze_with_gemini(
    transkrip_lengkap: str,
    cfg,
    logger_callback=None,
) -> list[dict]:
    """Analyse transcript with Gemini AI."""
    import google.genai as genai
    from google.genai import types

    print(f"[3/3] Analyzing Top {cfg.jumlah_clip} best moments using Gemini...")

    prompt = get_analysis_prompt(transkrip_lengkap, cfg.jumlah_clip, cfg.durasi_hook, cfg=cfg)

    # JSON Schema definitions (same as before)
    schema_broll = {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "start_time": {"type": "NUMBER"},
                "end_time": {"type": "NUMBER"},
                "search_query": {"type": "STRING"},
            },
            "required": ["start_time", "end_time", "search_query"],
        },
    }

    schema_visual_broll_hook = {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "broll_idea": {"type": "STRING"},
                "search_keyword": {"type": "STRING"},
                "why_it_works": {"type": "STRING"},
            },
            "required": ["broll_idea", "search_keyword", "why_it_works"],
        },
    }

    schema_typography = {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "kata_utama": {"type": "STRING"},
                "scale_level": {"type": "INTEGER"},
                "style": {"type": "STRING"},
                "animasi": {"type": "STRING"},
            },
            "required": ["kata_utama", "scale_level", "style", "animasi"],
        },
    }

    schema_klasifikasi = {
        "type": "OBJECT",
        "properties": {
            "tipe_akun": {"type": "STRING"},
            "akun_tujuan": {"type": "STRING"},
            "confidence": {"type": "INTEGER"},
            "angle_utama": {"type": "STRING"},
            "alasan": {"type": "STRING"},
            "kata_kunci_pendukung": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
            },
            "bio_akun": {"type": "STRING"},
            "alternatif_akun": {
                "type": "OBJECT",
                "properties": {
                    "tipe_akun": {"type": "STRING"},
                    "akun_tujuan": {"type": "STRING"},
                    "alasan": {"type": "STRING"},
                },
                "required": ["tipe_akun", "akun_tujuan", "alasan"],
            },
        },
        "required": ["tipe_akun", "akun_tujuan", "confidence", "angle_utama", "alasan", "kata_kunci_pendukung", "bio_akun", "alternatif_akun"],
    }

    client = genai.Client(
        api_key=cfg.api_key_gemini,
        http_options=types.HttpOptions(
            timeout=REQUEST_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )

    gemini_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema={
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "rank": {"type": "INTEGER"},
                    "viral_score": {"type": "INTEGER"},
                    "hook_start_time": {"type": "NUMBER"},
                    "hook_end_time": {"type": "NUMBER"},
                    "start_time": {"type": "NUMBER"},
                    "end_time": {"type": "NUMBER"},
                    "typography_plan": schema_typography,
                    "broll_list": schema_broll,
                    "recommended_visual_broll_hook": schema_visual_broll_hook,
                    "alasan": {"type": "STRING"},
                    "bgm_mood": {"type": "STRING"},
                    "title_indonesia": {"type": "STRING"},
                    "title_inggris": {"type": "STRING"},
                    "hastag": {"type": "STRING"},
                    "description_hook": {"type": "STRING"},
                    "description_context": {"type": "STRING"},
                    "keyword_tags": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "tiktok_title_id": {"type": "STRING"},
                    "tiktok_caption_id": {"type": "STRING"},
                    "tiktok_caption": {"type": "STRING"},
                    "klasifikasi_akun": schema_klasifikasi,
                    "hook_v2": {
                        "type": "OBJECT",
                        "properties": {
                            "enabled": {"type": "BOOLEAN"},
                            "items": {
                                "type": "ARRAY",
                                "items": {
                                    "type": "OBJECT",
                                    "properties": {
                                        "start_time": {"type": "NUMBER"},
                                        "end_time": {"type": "NUMBER"},
                                        "text": {"type": "STRING"},
                                    },
                                    "required": ["start_time", "end_time", "text"],
                                },
                            },
                            "transition": {
                                "type": "OBJECT",
                                "properties": {
                                    "type": {"type": "STRING"},
                                },
                                "required": ["type"],
                            },
                        },
                        "required": ["enabled", "items", "transition"],
                    },
                    "keep_segments": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "start_time": {"type": "NUMBER"},
                                "end_time": {"type": "NUMBER"},
                            },
                            "required": ["start_time", "end_time"],
                        },
                    },
                },
                "required": [
                    "rank", "viral_score", "hook_start_time", "hook_end_time",
                    "start_time", "end_time", "typography_plan",
                    "broll_list", "recommended_visual_broll_hook", "alasan", "bgm_mood",
                    "title_indonesia", "title_inggris", "hastag",
                    "description_hook", "description_context",
                    "keyword_tags", "tiktok_title_id",
                    "tiktok_caption_id", "tiktok_caption",
                    "klasifikasi_akun", "hook_v2", "keep_segments",
                ],
            },
        },
    )

    return _generate_json_with_retry(
        client=client,
        model=cfg.gemini_model,
        fallback_model=getattr(cfg, "gemini_fallback_model", None),
        contents=prompt,
        config=gemini_config,
        logger_callback=logger_callback,
    )