"""
clipping.studio.subtitle_engine

Fixes three major subtitle bugs:
  1. Marathi/compound transliteration overflowing off frame edges (unreadable/clipped).
     Measures true pixel width with PIL ImageFont and auto-breaks across 2 balanced lines,
     or scales down \\fscx/\\fscy if it still exceeds SAFE_WIDTH.
  2. Keyword/karaoke collisions: Keyword moments replace or cleanly hierarchy the caption slot
     so they never awkwardly stack or overlap.
  3. Missing punctuation: Aligns punctuated sentences onto raw Whisper words via difflib.
"""

import difflib
import os
import re
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict
from PIL import ImageFont

PLAY_RES_X = 1080
PLAY_RES_Y = 1920
SAFE_MARGIN_L = 60
SAFE_MARGIN_R = 60
SAFE_WIDTH = PLAY_RES_X - SAFE_MARGIN_L - SAFE_MARGIN_R  # 960
KARAOKE_FONT_SIZE = 64
KEYWORD_FONT_SIZE = 78
MIN_FONT_SCALE = 0.55  # Never shrink below 55% of base size

_font_cache: Dict[Tuple[str, int], ImageFont.FreeTypeFont] = {}


def _get_font(font_path_or_name: str, font_size: int) -> ImageFont.FreeTypeFont:
    key = (font_path_or_name, font_size)
    if key in _font_cache:
        return _font_cache[key]

    # Check direct path
    cand_path = font_path_or_name
    if not os.path.exists(cand_path):
        # Check custom_fonts directory
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "custom_fonts"))
        p = os.path.join(base, os.path.basename(font_path_or_name))
        if os.path.exists(p):
            cand_path = p
        elif os.path.exists(font_path_or_name + ".ttf"):
            cand_path = font_path_or_name + ".ttf"

    try:
        font = ImageFont.truetype(cand_path, font_size)
    except Exception:
        # Fallback to default truetype font or Arial
        try:
            font = ImageFont.truetype("Arial.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

    _font_cache[key] = font
    return font


def measure_width(text: str, font_size: int, font_path: str = "Montserrat-Bold.ttf") -> int:
    font = _get_font(font_path, font_size)
    if hasattr(font, "getbbox"):
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0]
    elif hasattr(font, "getlength"):
        return int(font.getlength(text))
    return len(text) * int(font_size * 0.6)


def fit_line(
    words: List[str],
    font_size: int,
    max_width: int = SAFE_WIDTH,
    font_path: str = "Montserrat-Bold.ttf",
) -> Tuple[List[List[str]], float]:
    """
    Given a list of words, returns (wrapped_lines_as_word_lists, font_scale).
    Breaks into up to 2 lines at word boundaries; if it still overflows,
    returns a font_scale < 1.0 to apply via \\fscx\\fscy.
    """
    if not words:
        return [[]], 1.0

    full_text = " ".join(words)
    width = measure_width(full_text, font_size, font_path)

    if width <= max_width:
        return [words], 1.0

    # Try 2-line break at the midpoint word boundary that best balances width
    best_split = None
    best_diff = float("inf")
    for i in range(1, len(words)):
        line1 = " ".join(words[:i])
        line2 = " ".join(words[i:])
        w1 = measure_width(line1, font_size, font_path)
        w2 = measure_width(line2, font_size, font_path)
        if w1 <= max_width and w2 <= max_width:
            diff = abs(w1 - w2)
            if diff < best_diff:
                best_diff = diff
                best_split = (words[:i], words[i:])

    if best_split:
        return [best_split[0], best_split[1]], 1.0

    # Even 2 lines don't fit (e.g. very long word or compound transliteration)
    scale = max(MIN_FONT_SCALE, max_width / max(width, 1))
    return [words], scale


def reinsert_punctuation(whisper_words: List[str], punctuated_sentence: str) -> List[str]:
    """
    Aligns raw Whisper words (no punctuation) against the punctuated sentence
    and transfers trailing punctuation back onto the matching Whisper word.
    """
    if not punctuated_sentence or not whisper_words:
        return whisper_words

    punct_tokens = re.findall(r"[\w']+[.,!?]*|[.,!?]", punctuated_sentence)
    punct_words_clean = [re.sub(r"[.,!?]+$", "", t).lower() for t in punct_tokens]
    whisper_clean = [w.lower() for w in whisper_words]

    matcher = difflib.SequenceMatcher(None, whisper_clean, punct_words_clean)
    result = list(whisper_words)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                src_word = punct_tokens[j1 + offset]
                result[i1 + offset] = src_word
    return result


@dataclass
class WordTiming:
    word: str
    start: float
    end: float
    highlight: bool = False


@dataclass
class KeywordMoment:
    text: str
    start: float
    end: float
    scale_level: int = 2
