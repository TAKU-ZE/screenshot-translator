# -*- coding: utf-8 -*-
"""
OCR client backed by SiliconFlow's free Vision-Language Model API.

Apply for a free API key at: https://cloud.siliconflow.cn/

This module exposes the same interface as a traditional OCR HTTP service
so the rest of the app does not need to know about VLM specifics.
We synthesize per-line bounding boxes from the model's text output so
downstream paragraph / code detection logic keeps working.
"""
import base64
from typing import Dict, List

import requests

from config import (
    OCR_API_URL, OCR_MODEL, OCR_API_KEY, assert_ocr_configured,
)


_OCR_PROMPT = (
    "Extract all visible text from this image. "
    "Preserve the original line breaks. "
    "Output the raw text only, no explanation, no markdown formatting."
)


def _call_vlm(image_bytes: bytes) -> str:
    """Send the image to the VLM, return the raw text it extracts."""
    assert_ocr_configured()
    img_b64 = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": OCR_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                },
                {"type": "text", "text": _OCR_PROMPT},
            ],
        }],
        "stream": False,
        "temperature": 0.0,
    }
    headers = {
        "Authorization": f"Bearer {OCR_API_KEY}",
        "Content-Type": "application/json",
    }
    resp = requests.post(OCR_API_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"unexpected VLM response: {data}") from e


def _text_to_pseudo_ocr(text: str) -> Dict:
    """Wrap plain VLM text into the bbox-bearing structure the app expects.

    Each non-empty line gets a synthetic 800-wide bounding box on its own
    row. Empty lines insert an extra vertical gap so the downstream paragraph
    detector (Y-gap based) recognises blank lines as paragraph breaks.
    """
    rec_texts: List[str] = []
    dt_polys: List[List[List[int]]] = []
    y = 10
    line_h = 30
    para_extra = 30  # extra gap added by a blank line
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.strip():
            rec_texts.append(line)
            dt_polys.append([
                [0, y], [800, y], [800, y + line_h], [0, y + line_h],
            ])
            y += line_h + 4  # small inter-line gap
        else:
            y += para_extra
    return {
        "errorCode": 0,
        "result": {
            "ocrResults": [{
                "prunedResult": {
                    "rec_texts": rec_texts,
                    "dt_polys": dt_polys,
                }
            }]
        },
    }


def ocr_image(image_bytes: bytes) -> Dict:
    """Returns a dict with the same shape as the legacy PaddleX serving response."""
    text = _call_vlm(image_bytes)
    return _text_to_pseudo_ocr(text)


def ocr_image_text(image_bytes: bytes) -> str:
    """Returns the recognised text only, lines joined by newline."""
    return _call_vlm(image_bytes).strip()
