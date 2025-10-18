# -*- coding: utf-8 -*-
"""
Example local config. Copy this file to `config_local.py` and edit it
if you prefer file-based config over environment variables.

`config_local.py` is gitignored — your real keys never get committed.
"""

# Get a free SiliconFlow API key at: https://cloud.siliconflow.cn/
SILICONFLOW_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# Optional overrides
OCR_MODEL = "deepseek-ai/DeepSeek-OCR"   # or "PaddlePaddle/PaddleOCR-VL"
OCR_API_URL = "https://api.siliconflow.cn/v1/chat/completions"
