# -*- coding: utf-8 -*-
"""
Configuration loaded from environment variables.

Set these in your shell before running:
    Windows PowerShell:
        $env:SILICONFLOW_API_KEY = "sk-xxxxxxxxxxxx"
    Windows CMD:
        set SILICONFLOW_API_KEY=sk-xxxxxxxxxxxx
    Linux / macOS:
        export SILICONFLOW_API_KEY=sk-xxxxxxxxxxxx

You can also copy `config.example.py` to `config_local.py` and edit it,
then `from config_local import *` overrides values here.

Apply for a free SiliconFlow API key at:
    https://cloud.siliconflow.cn/
"""
import os

# ──────────────────────────────────────────────
# OCR  (SiliconFlow Vision-Language Model API)
# ──────────────────────────────────────────────
OCR_API_URL = os.environ.get(
    "OCR_API_URL", "https://api.siliconflow.cn/v1/chat/completions"
)
# Free models on SiliconFlow:
#   "deepseek-ai/DeepSeek-OCR"
#   "PaddlePaddle/PaddleOCR-VL"
OCR_MODEL = os.environ.get("OCR_MODEL", "deepseek-ai/DeepSeek-OCR")
OCR_API_KEY = os.environ.get("SILICONFLOW_API_KEY", "")

# ──────────────────────────────────────────────
# Translation (Google free public endpoint, no key required)
# ──────────────────────────────────────────────
GOOGLE_TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"

# ──────────────────────────────────────────────
# Hotkey & UI
# ──────────────────────────────────────────────
HOTKEY_VK = 0x70   # F1
HOTKEY_MOD = 0     # 0=none, 0x0002=Ctrl, 0x0001=Alt, 0x0004=Shift

PEN_COLOR = "#FF0000"
PEN_WIDTH = 3
IMAGE_FORMAT = "PNG"


# If config_local.py exists, let it override anything above (gitignored).
try:
    from config_local import *  # noqa: F401, F403
except ImportError:
    pass


def assert_ocr_configured():
    if not OCR_API_KEY:
        raise RuntimeError(
            "SILICONFLOW_API_KEY is not set.\n"
            "Apply for a free key at https://cloud.siliconflow.cn/ "
            "then either set the env var SILICONFLOW_API_KEY "
            "or copy src/config.example.py to src/config_local.py and edit it."
        )
