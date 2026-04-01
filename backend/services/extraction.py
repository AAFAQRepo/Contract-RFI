"""
Document extraction + chunking service — powered by Docling.

Single entry point:
    extract_and_chunk(file_bytes, filename)
        → (lc_docs, full_text, page_count)

Handles all formats (PDF, DOCX, PPTX, images) with:
  - Docling layout parsing (tables, headings, sections)
  - Surya OCR for scanned / image-based documents
  - HybridChunker for document-aware chunking
"""

import os
import tempfile
import json
from pathlib import Path

from docling_surya import SuryaOcrOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.chunking import HybridChunker
from langchain_docling import DoclingLoader
from langchain_docling.loader import ExportType

from core.config import get_settings

settings = get_settings()

# ── Pipeline options (configured once) ────────────────────────────────

# Primary OCR pipeline (Surya)
_pipeline_options = PdfPipelineOptions(
    do_ocr=True,
    ocr_model="suryaocr",
    allow_external_plugins=True,
    ocr_options=SuryaOcrOptions(lang=["en", "ar"]),
)

_format_options = {
    InputFormat.PDF: PdfFormatOption(pipeline_options=_pipeline_options),
    InputFormat.IMAGE: PdfFormatOption(pipeline_options=_pipeline_options),
}

# Fallback OCR pipeline (Tesseract CLI) for Surya/runtime incompatibilities.
_fallback_pipeline_options = PdfPipelineOptions(
    do_ocr=True,
    ocr_model="tesseractcli",
    allow_external_plugins=False,
    # Tesseract uses ISO-639-2 language codes.
    ocr_options=TesseractCliOcrOptions(lang=["eng", "ara", "hin"]),
)

_fallback_format_options = {
    InputFormat.PDF: PdfFormatOption(pipeline_options=_fallback_pipeline_options),
    InputFormat.IMAGE: PdfFormatOption(pipeline_options=_fallback_pipeline_options),
}


def _patch_surya_cached_config_if_needed() -> int:
    """
    Surya model config compatibility fix.

    In some docling-surya/surya-ocr combinations, the decoder config loaded from
    cache misses `decoder.pad_token_id`, which causes:
      AttributeError: 'SuryaDecoderConfig' object has no attribute 'pad_token_id'

    If top-level `pad_token_id` exists, copy it into `decoder.pad_token_id`.
    Returns number of files patched.
    """
    base = Path.home() / ".cache" / "docling" / "models" / "SuryaOcr" / "text_recognition"
    if not base.exists():
        return 0

    patched = 0
    for cfg_path in sorted(base.glob("*/config.json")):
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            decoder = cfg.get("decoder")
            top_level_pad = cfg.get("pad_token_id")
            if isinstance(decoder, dict) and "pad_token_id" not in decoder and top_level_pad is not None:
                decoder["pad_token_id"] = top_level_pad
                cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                patched += 1
        except Exception:
            # Non-fatal: if patching fails, fallback path still handles extraction.
            pass

    return patched


def extract_and_chunk(
    file_bytes: bytes,
    filename: str,
) -> tuple[list, str, int]:
    """
    Extract text from a document and chunk it using Docling's HybridChunker.

    Args:
        file_bytes: Raw file content
        filename:   Original filename (used for extension detection)

    Returns:
        (lc_docs, full_text, page_count)
        - lc_docs:    list of LangChain Document objects (chunked)
        - full_text:  full markdown text of the document
        - page_count: number of pages detected
    """
    ext = Path(filename).suffix.lower()
    if not ext:
        ext = ".pdf"

    # Write bytes to a temp file (Docling needs a file path)
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        print(f"📄 Docling: parsing {filename} ...")

        patched_count = _patch_surya_cached_config_if_needed()
        if patched_count:
            print(f"🛠️  Patched Surya config in {patched_count} cached model file(s)")

        # ── Step 1: Convert document ──────────────────────────────
        converter = DocumentConverter(format_options=_format_options)
        try:
            result = converter.convert(tmp_path)
        except AttributeError as exc:
            # Known Surya/transformers incompatibility in some environments:
            # "SuryaDecoderConfig has no attribute pad_token_id".
            if "pad_token_id" not in str(exc):
                raise
            print("⚠️  Surya OCR init failed; falling back to Tesseract OCR")
            converter = DocumentConverter(format_options=_fallback_format_options)
            result = converter.convert(tmp_path)

        # Full markdown for language detection / summary
        full_text = result.document.export_to_markdown()

        # Count pages
        page_count = 0
        if hasattr(result.document, "pages") and result.document.pages:
            page_count = len(result.document.pages)
        elif hasattr(result, "pages"):
            page_count = len(result.pages)
        else:
            # Estimate from page references in the document
            page_count = _estimate_page_count(result.document)

        print(f"✅ Docling: parsed {page_count} pages, {len(full_text)} chars")

        # ── Step 2: Chunk with HybridChunker via DoclingLoader ────
        loader = DoclingLoader(
            file_path=tmp_path,
            export_type=ExportType.DOC_CHUNKS,
            converter=converter,
            chunker=HybridChunker(
                tokenizer=settings.EMBEDDING_MODEL,
                max_tokens=512,  # multilingual-e5-large-instruct max sequence length
            ),
        )
        lc_docs = loader.load()

        print(f"✂️  Docling: produced {len(lc_docs)} chunks")

        return lc_docs, full_text, page_count

    finally:
        os.unlink(tmp_path)


def _estimate_page_count(document) -> int:
    """Estimate page count from document item provenance data."""
    max_page = 0
    try:
        for item in getattr(document, "body", []):
            for prov in getattr(item, "prov", []):
                if hasattr(prov, "page_no"):
                    max_page = max(max_page, prov.page_no)
    except Exception:
        pass
    return max_page if max_page > 0 else 1
