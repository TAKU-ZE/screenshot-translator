# Screenshot Translator

> **An enterprise-grade desktop OCR + on-the-fly translation suite.**
> Capture any region of your screen with a single hotkey, get the recognised text instantly copied to your clipboard, or render a fully translated overlay rendered as Markdown-styled HTML — directly back onto your selection. Powered by state-of-the-art Vision-Language Models.

[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![PyQt5](https://img.shields.io/badge/Qt-PyQt5-41cd52)](https://riverbankcomputing.com/software/pyqt/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Status: Active](https://img.shields.io/badge/status-active-success)](#)

---

## Why this project?

Modern knowledge work is fragmented across applications written in dozens of
languages — proprietary CAD software in Japanese, command-line tools with
Russian docs, manga readers, foreign-language admin consoles, untranslatable
PDFs displayed inside browsers. The conventional workflow of *screenshot →
switch app → upload to web translator → copy back* breaks flow and adds
seconds of friction to every lookup.

**Screenshot Translator** collapses that loop into a single hotkey. Hit
`F1`, drag a region, and the tool runs an end-to-end pipeline through a
Vision-Language Model, segments the result, translates it line by line,
then paints a richly-formatted Markdown overlay back onto your screen at
the exact location of the original.

The project also doubles as a reference implementation of how to wire
modern multimodal LLM APIs into a polished native desktop UX.

---

## Features

### Capture & UX

- **Global hotkey capture** via Win32 `RegisterHotKey` — `F1` from anywhere, even when the app is minimised
- **Multi-monitor virtual desktop** support; per-screen pixmap composition for arbitrary topology and per-monitor DPI
- **Rubber-band region selection** with live size readout and 8-handle resize / drag once placed
- **Floating toolbar** auto-anchored to the selection, with one-click access to every action
- **Always-on-top pin window** with mouse-wheel zoom and frameless drag
- **System tray integration** with custom icon and context menu
- **Annotation layer** — red-pen free-hand drawing with `Ctrl+Z` undo
- **Clipboard-first workflow** — double-click any selection to copy the cropped image straight to clipboard

### OCR & Translation Pipeline

- **Cloud Vision-Language Models** via SiliconFlow — DeepSeek-OCR (3B params) or PaddleOCR-VL (0.9B), both on the **free tier**
- **Synthetic bounding boxes** generated from VLM text output keep the downstream paragraph / code-block detector decoupled from the OCR backend
- **Heuristic structure recovery** — paragraph breaks from Y-gap analysis, code-block detection from symbol density + keyword prefixes + path patterns
- **Bullet-list autodetection** — recognises `Title: content` patterns across the document and lifts them into a proper Markdown list
- **Batch line-aligned translation** via Google's free public endpoint, preserving 1:1 input/output mapping required by the renderer
- **Per-line failure isolation** — translation errors on individual lines fall back to source text instead of breaking the whole batch

### Rendering Engine

- **HTML rendering through QTextDocument** with an inline-style sheet (Qt's external CSS support is unreliable; we sidestep it entirely)
- **Custom `QAbstractTextDocumentLayout.PaintContext`** with palette override to force light text on dark backgrounds — the only reliable way in Qt to override the default text colour
- **Binary-search font sizing** — finds the largest font that lets all blocks fit inside the selection rectangle
- **Pixel-perfect text wrapping** with CJK-aware tokeniser (space-first, character-fallback)
- **Code blocks rendered with monospace + dark gutter**, preserving original whitespace via `white-space: pre-wrap`

### Engineering

- **Pure-Python, single-binary friendly** — only PyQt5, requests, mss, Pillow as runtime deps
- **Zero credentials in source** — all secrets loaded from environment variables; optional gitignored `config_local.py` overrides
- **Thread-safe async workers** — every OCR / translate call runs in a `QThread` and signals back to the GUI via Qt's `pyqtSignal` so the UI never blocks
- **Fully cross-platform on the rendering layer**; capture path tested on Windows 10/11 (multi-monitor, mixed DPI)

---

## Architecture

```
                ┌──────────────────────┐
                │  F1 Global Hotkey    │
                │  RegisterHotKey      │
                └──────────┬───────────┘
                           ▼
         ┌─────────────────────────────────┐
         │  ScreenshotOverlay (PyQt5)      │
         │  - virtual desktop composition  │
         │  - rubber-band selection        │
         │  - floating toolbar             │
         └────────────┬────────────────────┘
                      ▼
            ┌──────────────────┐
            │  selection.png   │
            └────────┬─────────┘
                     ▼
   ┌──────────────────────────────────────┐
   │  OcrWorker (QThread)                 │
   │  → SiliconFlow VLM API               │
   │     DeepSeek-OCR / PaddleOCR-VL      │
   │  ← raw text with line breaks         │
   │  → synthetic per-line bboxes         │
   └────────────────┬─────────────────────┘
                    ▼
   ┌──────────────────────────────────────┐
   │  Block builder                       │
   │  - merge same-line bboxes            │
   │  - detect paragraphs by Y-gap        │
   │  - classify lines as code or text    │
   │  - detect bullet patterns globally   │
   └────────────────┬─────────────────────┘
                    ▼
   ┌──────────────────────────────────────┐
   │  BatchTranslateWorker (QThread)      │
   │  → Google free translate endpoint    │
   │     line-by-line, rate-limited       │
   │  ← translated lines (1:1 mapping)    │
   └────────────────┬─────────────────────┘
                    ▼
   ┌──────────────────────────────────────┐
   │  HTML renderer                       │
   │  - inline-style block construction   │
   │  - QTextDocument + PaintContext      │
   │  - binary-search font sizing         │
   │  - draw to QPixmap                   │
   └────────────────┬─────────────────────┘
                    ▼
   ┌──────────────────────────────────────┐
   │  Overlay paint pass                  │
   │  drawPixmap(selection, overlay_pm)   │
   └──────────────────────────────────────┘
```

---

## Installation

### Prerequisites

- Python 3.9 or newer
- A free SiliconFlow account ([cloud.siliconflow.cn](https://cloud.siliconflow.cn/))

### Setup

```bash
git clone https://github.com/<your-username>/screenshot-translator.git
cd screenshot-translator
pip install -r requirements.txt
```

### Configure your SiliconFlow API key

1. Sign up at [cloud.siliconflow.cn](https://cloud.siliconflow.cn/) (free tier: 1 000 RPM, 80 K TPM, no credit card required)
2. Create an API key in **API Key Management**
3. Export it as an environment variable:

```powershell
# Windows PowerShell
$env:SILICONFLOW_API_KEY = "sk-xxxxxxxxxxxx"
```

```bash
# macOS / Linux
export SILICONFLOW_API_KEY=sk-xxxxxxxxxxxx
```

Alternatively, copy `src/config.example.py` to `src/config_local.py` and edit it. The local config is gitignored so your key never gets committed.

### Run

```bash
cd src
python main.py
```

A blue **S** icon appears in the system tray. Press `F1` to capture.

---

## Usage

| Action | Trigger |
|---|---|
| Capture region | `F1` or left-click tray icon |
| Cancel | Right-click overlay or `Esc` |
| Copy raw screenshot | Double-click selection |
| Extract text to clipboard | Toolbar `T` |
| Translate overlay | Toolbar `Tr` |
| Red-pen annotation | Toolbar `✏` |
| Pin to screen | Toolbar `📌` |
| Save as PNG | Toolbar `💾` |
| Quit | Tray menu → Quit |

---

## Tech Stack

| Layer | Technology |
|---|---|
| GUI framework | **PyQt5** (Qt 5.15+) |
| Screen capture | **mss** for cross-monitor virtual-desktop grab |
| Image handling | **Pillow** |
| HTTP client | **requests** |
| OCR backend | **SiliconFlow** Vision-Language Model API (OpenAI-compatible) |
| OCR models | DeepSeek-OCR (3B), PaddleOCR-VL (0.9B) |
| Translation | Google Translate undocumented public endpoint |
| Hotkey | Win32 `RegisterHotKey` via `ctypes` |
| Async model | `QThread` + `pyqtSignal` |
| Rendering | `QTextDocument` + `QAbstractTextDocumentLayout.PaintContext` |

---

## Configuration Reference

All settings live in `src/config.py`. Override via environment variable or `src/config_local.py`.

| Variable | Default | Description |
|---|---|---|
| `SILICONFLOW_API_KEY` | *(required)* | Bearer token for SiliconFlow OCR API |
| `OCR_API_URL` | `https://api.siliconflow.cn/v1/chat/completions` | OpenAI-compatible chat endpoint |
| `OCR_MODEL` | `deepseek-ai/DeepSeek-OCR` | Any vision-capable model on SiliconFlow |
| `HOTKEY_VK` | `0x70` (F1) | Win32 virtual key code |
| `HOTKEY_MOD` | `0` | Modifier mask (`0x0002` Ctrl, `0x0001` Alt, `0x0004` Shift) |
| `PEN_COLOR` | `#FF0000` | Annotation pen colour |
| `PEN_WIDTH` | `3` | Annotation pen width in pixels |

---

## Roadmap

- [ ] Linux / macOS hotkey backends (currently Windows-only via Win32 API)
- [ ] Local OCR backend option (PaddleX HTTP, Tesseract, etc.) via plugin interface
- [ ] Multiple translation provider strategies (DeepL, Azure, OpenAI, local LLM)
- [ ] Table layout recovery via PP-StructureV3 or VLM-driven Markdown table parsing
- [ ] User-defined CSS theme for the overlay
- [ ] One-click bundling via PyInstaller / Briefcase

---

## Project Layout

```
screenshot-translator/
├── README.md
├── LICENSE                       # MIT
├── .gitignore
├── requirements.txt
└── src/
    ├── main.py                   # GUI, capture overlay, hotkey, tray, rendering
    ├── config.py                 # env-driven configuration with local override
    ├── config.example.py         # template for src/config_local.py
    ├── ocr_client.py             # SiliconFlow VLM client
    └── translator.py             # Google free-tier translate client
```

---

## Implementation Notes

**Why synthetic bounding boxes?** Vision-Language Models return free-form text, not structured layout information. To reuse the existing paragraph-detection and code-block-classification logic — which expect bbox-based input — the OCR client emits one synthetic 800-px-wide row per line, with extra vertical gaps inserted whenever the VLM produced a blank line. The downstream pipeline cannot tell the difference.

**Why HTML, not Markdown?** `QTextDocument.setMarkdown()` exists but its CSS subset has spotty support for paragraph margins, list indentation, and font colour. `setHtml()` with **inline** styles produces consistent results across Qt versions and platforms. The Markdown-style appearance is implemented manually in `_blocks_to_html()`.

**Why a custom `PaintContext`?** Qt's default text colour comes from the application palette, not the document stylesheet. Even with `body { color: ... }` set via `setDefaultStyleSheet`, the rendered text remained black. The fix is to construct a `QAbstractTextDocumentLayout.PaintContext`, override its palette's `Text` and `WindowText` roles, and call `documentLayout().draw(painter, ctx)` directly.

**Why binary search for font size?** A single font size cannot serve every selection — a 200×100 selection holding 200 words needs a tiny font, while a 1000×600 selection holding 30 words can show them comfortably large. Binary searching `font-size` between 9 px and 28 px against the rendered document height converges in 4–5 iterations and produces visually optimal results.

---

## Contributing

Issues and pull requests welcome. The project deliberately keeps the dependency footprint small; any new dependency should justify its weight.

---

## License

MIT — see [LICENSE](LICENSE).
