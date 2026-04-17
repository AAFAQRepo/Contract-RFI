"""
Falcon-OCR service for PDF text extraction.

Replaces Docling+Surya for scanned/image-based PDFs by rendering pages
to images and running tiiuae/Falcon-OCR on each page.
"""

import io
from typing import Optional

import fitz  # pymupdf
import torch
from PIL import Image
from transformers import AutoModelForCausalLM

from core.config import get_settings

settings = get_settings()

# ── Model (loaded once, cached globally) ──────────────────────────────
_falcon_model: Optional[AutoModelForCausalLM] = None

_SKIP_CATEGORIES = {"figure", "image", "picture"}
_CAT_TABLE = "table"


def get_falcon_model() -> AutoModelForCausalLM:
    global _falcon_model
    if _falcon_model is None:
        print(f"⏳ Loading Falcon-OCR: {settings.FALCON_OCR_MODEL_ID}")
        _falcon_model = AutoModelForCausalLM.from_pretrained(
            settings.FALCON_OCR_MODEL_ID,
            trust_remote_code=True,
            torch_dtype=torch.bfloat16,
            device_map="auto",
        ).eval()
        print("✅ Falcon-OCR loaded")
    return _falcon_model


def extract_text_from_pdf(file_bytes: bytes) -> tuple[str, int]:
    """
    Render a PDF to images and extract text with Falcon-OCR.

    Returns:
        (full_markdown_text, page_count)
    """
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    model = get_falcon_model()
    render_scale = getattr(settings, "FALCON_OCR_RENDER_SCALE", 2.0)
    use_layout = getattr(settings, "FALCON_OCR_USE_LAYOUT", True)

    page_texts: list[str] = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        mat = fitz.Matrix(render_scale, render_scale)
        pix = page.get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")

        if use_layout:
            page_text = _extract_page_with_layout(img, model)
        else:
            raw = model.generate(img)
            page_text = raw[0].strip() if raw else ""

        page_texts.append(f"## Page {page_idx + 1}\n\n{page_text}")

    doc.close()
    full_text = "\n\n".join(page_texts)
    return full_text, len(page_texts)


def _extract_page_with_layout(image: Image.Image, model) -> str:
    """Run Falcon-OCR generate_with_layout and assemble markdown."""
    results = model.generate_with_layout(image)
    detections = results[0] if results else []

    if not detections:
        # Fallback to plain generation
        raw = model.generate(image)
        return raw[0].strip() if raw else ""

    # Reading order: top-to-bottom, left-to-right
    detections.sort(key=lambda d: (d["bbox"][1], d["bbox"][0]))

    parts: list[str] = []
    for det in detections:
        cat = det.get("category", "text")
        bbox = det.get("bbox", [])

        if cat in _SKIP_CATEGORIES:
            continue

        if cat == _CAT_TABLE and bbox:
            x0, y0, x1, y1 = [int(v) for v in bbox]
            crop = image.crop((x0, y0, x1, y1))
            table_result = model.generate(crop, category=_CAT_TABLE)
            html = table_result[0].strip() if table_result else det.get("text", "")
            if html:
                parts.append(f"\n### Table\n{html}\n")
        else:
            t = det.get("text", "").strip()
            if t:
                parts.append(t)

    return "\n\n".join(parts)
