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
from pathlib import Path

from docling_surya import SuryaOcrOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.chunking import HybridChunker
from langchain_docling import DoclingLoader
from langchain_docling.loader import ExportType

from core.config import get_settings

settings = get_settings()

# ── Pipeline options (configured once) ────────────────────────────────

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

        # ── Step 1: Convert document ──────────────────────────────
        converter = DocumentConverter(format_options=_format_options)
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
