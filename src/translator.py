# -*- coding: utf-8 -*-
"""
Translation client - uses Google's free public translate endpoint.

No API key required. Note this is an undocumented public endpoint and may
break at any time. For production use, swap to DeepL / Google Cloud /
your-own-LLM as needed.
"""
import time
from typing import List

import requests

from config import GOOGLE_TRANSLATE_URL


# Map our short codes to Google's
_LANG_MAP_TO_GOOGLE = {
    "zh": "zh-CN", "cht": "zh-TW", "jp": "ja", "kor": "ko",
}


def translate(text: str, from_lang: str = "auto", to_lang: str = "zh") -> str:
    """Translate a single string. Empty input returns empty."""
    if not text or not text.strip():
        return ""
    return _google_translate(text, from_lang, to_lang)


def translate_lines(lines: List[str], from_lang: str = "auto", to_lang: str = "zh") -> List[str]:
    """Translate a list of strings, preserving 1:1 mapping.

    On per-line failure, original text is kept so callers always get
    len(out) == len(lines).
    """
    out: List[str] = []
    for line in lines:
        if not line or not line.strip():
            out.append("")
            continue
        try:
            out.append(_google_translate(line, from_lang, to_lang).strip())
        except Exception as e:
            print(f"[translate_lines] {type(e).__name__}: {e} | line={line!r}")
            out.append(line)
        # Be polite to Google's free endpoint
        time.sleep(0.05)
    return out


def _google_translate(text: str, from_lang: str, to_lang: str) -> str:
    sl = _LANG_MAP_TO_GOOGLE.get(from_lang, from_lang)
    tl = _LANG_MAP_TO_GOOGLE.get(to_lang, to_lang)
    resp = requests.get(
        GOOGLE_TRANSLATE_URL,
        params={"client": "gtx", "sl": sl, "tl": tl, "dt": "t", "q": text},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(part[0] for part in data[0] if part and part[0])
