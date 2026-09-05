"""
General helper utilities for Studio rendering workflow.
"""


def format_seconds(seconds):
    """
    Format a duration in seconds into HH:MM:SS.

    Args:
        seconds: Numeric duration in seconds.

    Returns:
        Duration string in `HH:MM:SS` format, clamped to non-negative.
    """
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def escape_ffmpeg_filter_value(value: str) -> str:
    """
    Escape a value so it is safe in FFmpeg filter expressions.

    Args:
        value: Raw value to place inside an FFmpeg filter string.

    Returns:
        Escaped value string for FFmpeg filter usage.
    """
    return str(value).replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'")


def devanagari_to_hinglish(text: str) -> str:
    """
    Convert Hindi / Devanagari script into natural English-based romanized Hindi (Hinglish).
    e.g. 'आज कब आने वाला है' -> 'aaj kab aane wala hai'
    """
    if not text:
        return text

    # Check if string contains Devanagari
    if not any('\u0900' <= ch <= '\u097F' for ch in text):
        return text

    vowels = {
        'अ': 'a', 'आ': 'aa', 'इ': 'i', 'ई': 'ee', 'उ': 'u', 'ऊ': 'oo', 'ऋ': 'ri',
        'ए': 'e', 'ऐ': 'ai', 'ओ': 'o', 'औ': 'au', 'अं': 'an', 'अः': 'ah'
    }
    matras = {
        'ा': 'a', 'ि': 'i', 'ी': 'ee', 'ु': 'u', 'ू': 'oo', 'ृ': 'ri',
        'े': 'e', 'ै': 'ai', 'ो': 'o', 'ौ': 'au', 'ं': 'n', 'ँ': 'n', 'ः': 'h',
        '्': ''  # halant
    }
    consonants = {
        'क': 'k', 'ख': 'kh', 'ग': 'g', 'घ': 'gh', 'ङ': 'ng',
        'च': 'ch', 'छ': 'chh', 'ज': 'j', 'झ': 'jh', 'ञ': 'ny',
        'ट': 't', 'ठ': 'th', 'ड': 'd', 'ढ': 'dh', 'ण': 'n',
        'त': 't', 'थ': 'th', 'द': 'd', 'ध': 'dh', 'न': 'n',
        'प': 'p', 'फ': 'ph', 'ब': 'b', 'भ': 'bh', 'म': 'm',
        'य': 'y', 'र': 'r', 'ल': 'l', 'व': 'v',
        'श': 'sh', 'ष': 'sh', 'स': 's', 'ह': 'h',
        'क्ष': 'ksh', 'त्र': 'tr', 'ज्ञ': 'gya',
        'क़': 'q', 'ख़': 'kh', 'ग़': 'gh', 'ज़': 'z', 'ड़': 'r', 'ढ़': 'rh', 'फ़': 'f'
    }
    common_words = {
        'आज': 'aaj', 'कब': 'kab', 'आने': 'aane', 'वाला': 'wala', 'वाली': 'wali',
        'वाले': 'wale', 'है': 'hai', 'हैं': 'hain', 'हो': 'ho', 'था': 'tha',
        'थी': 'thee', 'थे': 'the', 'मोस्ट': 'most', 'रोमांटिक': 'romantic',
        'क्या': 'kya', 'क्यों': 'kyun', 'कैसे': 'kaise', 'कहा': 'kaha',
        'कहाँ': 'kahan', 'यहाँ': 'yahan', 'वहाँ': 'wahan', 'यह': 'yeh', 'वह': 'woh',
        'नहीं': 'nahi', 'हाँ': 'haan', 'बहुत': 'bahut', 'अच्छा': 'achha',
        'अच्छी': 'achhi', 'अच्छे': 'achhe', 'करना': 'karna', 'कर': 'kar',
        'रहा': 'raha', 'रही': 'rahi', 'रहे': 'rahe', 'बात': 'baat',
        'लोग': 'log', 'समय': 'samay', 'दिन': 'din', 'रात': 'raat',
        'घर': 'ghar', 'काम': 'kaam', 'चीज': 'cheez', 'वीडियो': 'video',
        'चीट': 'cheat', 'फ़ोन': 'phone', 'फोन': 'phone', 'मूव': 'move',
        'ऑन': 'on', 'किस': 'kis', 'प्यार': 'pyaar', 'दोस्त': 'dost', 'जिंदगी': 'zindagi'
    }

    res = []
    for w in text.split():
        clean = w.strip('.,!?:;\"\'()[]{}')
        punct_prefix = w[:len(w) - len(w.lstrip('.,!?:;\"\'()[]{}'))]
        punct_suffix = w[len(w.rstrip('.,!?:;\"\'()[]{}')):]

        if clean in common_words:
            res.append(punct_prefix + common_words[clean] + punct_suffix)
        elif not any('\u0900' <= ch <= '\u097F' for ch in clean):
            res.append(w)
        else:
            i = 0
            n = len(clean)
            converted = []
            while i < n:
                ch = clean[i]
                if ch in vowels:
                    converted.append(vowels[ch])
                    i += 1
                elif ch in consonants:
                    c_sound = consonants[ch]
                    if i + 1 < n:
                        next_ch = clean[i + 1]
                        if next_ch == '्':
                            converted.append(c_sound)
                            i += 2
                        elif next_ch in matras:
                            converted.append(c_sound + matras[next_ch])
                            i += 2
                        elif next_ch in consonants or next_ch in vowels:
                            converted.append(c_sound + 'a')
                            i += 1
                        else:
                            converted.append(c_sound)
                            i += 1
                    else:
                        converted.append(c_sound)
                        i += 1
                elif ch in matras:
                    converted.append(matras[ch])
                    i += 1
                else:
                    converted.append(ch)
                    i += 1
            res.append(punct_prefix + ''.join(converted) + punct_suffix)

    return ' '.join(res)

