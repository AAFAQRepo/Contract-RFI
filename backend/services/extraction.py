"""
Document extraction + chunking service — powered by MinerU.

Single entry point:
    extract_and_chunk(file_bytes, filename)
        → (lc_docs, full_text, page_count)

Handles all formats (PDF, DOCX, images) with:
  - MinerU `pipeline` backend (CPU-safe, macOS-compatible)
  - parse_method="auto"  → auto-detects text-native vs scanned/OCR PDFs
  - Rule-based chunker over MinerU's content_list.json for rich metadata

Output metadata shape is intentionally kept identical to the former
Docling-based pipeline so downstream embedding.py / celery_app.py code
requires no changes:
    metadata = {
        "dl_meta": {
            "headings": [<section_heading>],
            "doc_items": [{"prov": [{"page_no": <int>}]}],
        }
    }
"""

import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from core.config import get_settings

settings = get_settings()

# ─────────────────────────────────────────────────────────────────────────
# Internal data types
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class _ChunkDoc:
    """Minimal document shape used by downstream embedding/storage code."""
    page_content: str
    metadata: dict


# ─────────────────────────────────────────────────────────────────────────
# Chunking helpers
# ─────────────────────────────────────────────────────────────────────────

_MAX_WORDS = 600          # Approx token budget per chunk
_MIN_WORDS = 30           # Merge chunks shorter than this into the next


def _estimate_words(text: str) -> int:
    return len(text.split())


def _heading_from_block(block: dict) -> str | None:
    """
    Extract heading text from a MinerU content_list block.
    MinerU marks headings with type='text' and level in {1,2,3,...}
    or type='title'.
    """
    btype = block.get("type", "")
    if btype in ("title",):
        return (block.get("text") or "").strip() or None
    # Some versions use level field for section headings
    if btype == "text" and block.get("level", 0) in (1, 2):
        text = (block.get("text") or "").strip()
        # Heuristic: short text blocks that look like headings
        if text and len(text) < 120 and not text.endswith("."):
            return text
    return None


def _page_from_block(block: dict) -> int:
    """Extract 1-based page number from a content_list block."""
    # MinerU content_list uses 'page_id' (0-based in older versions, check both)
    page_id = block.get("page_id")
    if page_id is not None:
        return int(page_id) + 1  # convert to 1-based
    # Fallback: some versions use 'page_no' directly (1-based)
    page_no = block.get("page_no")
    if page_no is not None:
        return int(page_no)
    return 0


def _block_text(block: dict) -> str:
    """Get the rendered text of a content block."""
    btype = block.get("type", "")
    # Tables are already rendered as markdown by MinerU
    if btype == "table":
        return (block.get("table_caption") or "") + "\n" + (block.get("table_body") or "")
    # Images: use caption only
    if btype in ("image", "figure"):
        return (block.get("img_caption") or "").strip()
    return (block.get("text") or "").strip()


def _build_chunks_from_content_list(
    content_list: list[dict],
) -> list[_ChunkDoc]:
    """
    Convert MinerU's content_list into _ChunkDoc objects.

    Strategy:
      - Walk blocks in reading order.
      - Track the current section heading.
      - Accumulate text until _MAX_WORDS is reached, then flush.
      - Blocks shorter than _MIN_WORDS are merged with the next.
    """
    chunks: list[_ChunkDoc] = []
    current_heading = ""
    current_page = 0
    buffer_texts: list[str] = []
    buffer_page = 0

    def _flush():
        nonlocal buffer_texts, buffer_page
        text = "\n\n".join(t for t in buffer_texts if t).strip()
        if not text:
            buffer_texts = []
            return
        chunks.append(
            _ChunkDoc(
                page_content=text,
                metadata={
                    "dl_meta": {
                        "headings": [current_heading] if current_heading else [],
                        "doc_items": [{"prov": [{"page_no": buffer_page}]}],
                    }
                },
            )
        )
        buffer_texts = []

    for block in content_list:
        btype = block.get("type", "")
        page = _page_from_block(block)
        if page:
            current_page = page

        # Update running heading tracker
        heading = _heading_from_block(block)
        if heading:
            current_heading = heading
            # Flush any accumulated text before starting new section
            _flush()
            buffer_page = current_page
            # Include heading as first line of new chunk
            buffer_texts.append(f"## {heading}")
            continue

        # Skip empty / pure image blocks with no caption
        text = _block_text(block)
        if not text:
            continue

        # If buffer is empty, record the starting page
        if not buffer_texts:
            buffer_page = current_page

        # Tables always flush before and after (preserve as standalone chunks)
        if btype == "table":
            _flush()
            buffer_page = current_page
            chunks.append(
                _ChunkDoc(
                    page_content=text.strip(),
                    metadata={
                        "dl_meta": {
                            "headings": [current_heading] if current_heading else [],
                            "doc_items": [{"prov": [{"page_no": current_page}]}],
                        }
                    },
                )
            )
            continue

        buffer_texts.append(text)

        # Flush when budget exceeded
        if _estimate_words("\n\n".join(buffer_texts)) >= _MAX_WORDS:
            _flush()
            buffer_page = current_page

    _flush()  # Remainder

    # ── Merge tiny trailing chunks ─────────────────────────────────────
    merged: list[_ChunkDoc] = []
    for chunk in chunks:
        if merged and _estimate_words(chunk.page_content) < _MIN_WORDS:
            # Append to previous chunk
            prev = merged[-1]
            prev.page_content = prev.page_content + "\n\n" + chunk.page_content
        else:
            merged.append(chunk)

    return merged


# ─────────────────────────────────────────────────────────────────────────
# Page-count helper
# ─────────────────────────────────────────────────────────────────────────

def _count_pages_from_content_list(content_list: list[dict]) -> int:
    """Derive page count from the max page_id seen in content blocks."""
    max_page = 0
    for block in content_list:
        page = _page_from_block(block)
        if page > max_page:
            max_page = page
    return max_page if max_page > 0 else 1


# ─────────────────────────────────────────────────────────────────────────
# MinerU parse wrapper
# ─────────────────────────────────────────────────────────────────────────

def _is_text_native_pdf(file_bytes: bytes, ext: str) -> bool:
    """Quickly check if a PDF is digital/text-native to bypass OCR models."""
    if ext != ".pdf":
        return False
    try:
        import fitz # PyMuPDF
        doc = fitz.open("pdf", file_bytes)
        text_len = 0
        num_pages = len(doc)
        if num_pages == 0:
            return False
            
        # Check up to first 3 pages
        check_pages = min(3, num_pages)
        for i in range(check_pages):
            text_len += len(doc[i].get_text("text").strip())
        doc.close()
        
        # If we average > 150 chars per page, it's highly likely text-native
        return (text_len / check_pages) > 150
    except Exception as e:
        print(f"⚠️ PyMuPDF fast-check failed: {e}")
        return False


def _run_mineru(
    file_bytes: bytes,
    filename: str,
    tmp_dir: str,
) -> tuple[str, list[dict]]:
    """
    Write file to tmp_dir, run MinerU do_parse, and return
    (markdown_text, content_list).

    MinerU writes output under:
        <tmp_dir>/<stem>/<parse_method>/<stem>.md
    """
    stem = Path(filename).stem or "document"
    ext = Path(filename).suffix.lower() or ".pdf"
    input_path = os.path.join(tmp_dir, f"{stem}{ext}")

    with open(input_path, "wb") as f:
        f.write(file_bytes)

    # Build safe basename for MinerU output naming
    safe_stem = stem[:80]  # avoid overly long paths

    # ── Speed Optimization ─────────────────────────────────────────────
    # If it's a digital PDF, we force parse_method="txt" and disable heavy models.
    parse_method = "auto"
    if _is_text_native_pdf(file_bytes, ext):
        parse_method = "txt"
        os.environ["MINERU_FORMULA_ENABLE"] = "false"
        os.environ["MINERU_LAYOUT_ENABLE"] = "false"
        os.environ["MINERU_TABLE_ENABLE"] = "false"
        print("⚡ Text-native PDF detected. High-speed 'txt' path enabled (MFR/Layout disabled).")

    from mineru.cli.common import do_parse

    do_parse(
        output_dir=tmp_dir,
        pdf_file_names=[safe_stem],
        pdf_bytes_list=[file_bytes],
        p_lang_list=["en"],         # OCR language
        backend="pipeline",         # CPU-safe; models load only if needed
        parse_method=parse_method,  
        f_dump_md=True,
        f_dump_content_list=True,
        f_dump_middle_json=False,
        f_dump_model_json=False,
        f_dump_orig_pdf=False,
        f_draw_layout_bbox=False,
        f_draw_span_bbox=False,
    )

    # ── Locate output files properly ───────────────────────────────────
    # MinerU 3.0 creates: <output_dir>/<safe_stem>/<parse_method>/...
    # We use a robust glob search to find the files regardless of nesting.
    md_path = ""
    cl_path = ""
    
    # Precise search under the expected safe_stem directory first
    search_root = Path(tmp_dir) / safe_stem
    if not search_root.exists():
        search_root = Path(tmp_dir)

    # Find the largest .md file (usually the final output)
    md_files = sorted(search_root.rglob("*.md"), key=lambda p: p.stat().st_size, reverse=True)
    if md_files:
        md_path = str(md_files[0])
    
    # Find the best content_list.json (v2 preferred, then v1)
    cl_files = sorted(search_root.rglob("content_list*.json"), key=lambda p: p.name, reverse=True)
    if cl_files:
        cl_path = str(cl_files[0])

    # Read markdown
    markdown = ""
    if md_path and os.path.exists(md_path):
        with open(md_path, "r", encoding="utf-8") as f:
            markdown = f.read()
    else:
        print(f"⚠️  MinerU: No .md files found in {search_root}")

    # Read content_list
    content_list: list[dict] = []
    if cl_path and os.path.exists(cl_path):
        with open(cl_path, "r", encoding="utf-8") as f:
            content_list = json.load(f)
    else:
        print(f"⚠️  MinerU: No content_list.json found in {search_root}. Chunking will fall back to raw markdown split.")

    # PostgreSQL cannot store NUL bytes in TEXT columns
    markdown = markdown.replace("\x00", "")

    return markdown, content_list


# ─────────────────────────────────────────────────────────────────────────
# Fallback chunker (when content_list.json is missing)
# ─────────────────────────────────────────────────────────────────────────

def _chunk_markdown_fallback(markdown: str) -> list[_ChunkDoc]:
    """
    Simple markdown-section splitter used when content_list.json is absent.
    Splits on H1/H2/H3 headings, then enforces max word budget per chunk.
    """
    import re

    chunks: list[_ChunkDoc] = []
    heading_pat = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
    boundaries = [m.start() for m in heading_pat.finditer(markdown)]
    boundaries.append(len(markdown))

    sections: list[tuple[str, str]] = []
    prev = 0
    prev_heading = ""
    for i, start in enumerate(boundaries[:-1]):
        m = heading_pat.match(markdown, start)
        if m:
            sections.append((prev_heading, markdown[prev:start]))
            prev_heading = m.group(2).strip()
            prev = start
    sections.append((prev_heading, markdown[prev:]))

    for heading, body in sections:
        body = body.strip()
        if not body:
            continue
        words = body.split()
        for i in range(0, max(len(words), 1), _MAX_WORDS):
            chunk_text = " ".join(words[i : i + _MAX_WORDS])
            if chunk_text.strip():
                chunks.append(
                    _ChunkDoc(
                        page_content=chunk_text,
                        metadata={
                            "dl_meta": {
                                "headings": [heading] if heading else [],
                                "doc_items": [{"prov": [{"page_no": 0}]}],
                            }
                        },
                    )
                )
    return chunks


# ─────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────

def extract_and_chunk(
    file_bytes: bytes,
    filename: str,
) -> tuple[list, str, int]:
    """
    Extract text from a document and chunk it using MinerU.

    Uses MinerU's `pipeline` backend with `parse_method="auto"`:
      - Text-native PDFs  → fast text extraction (sub-second per page)
      - Scanned PDFs      → OCR via layout-analysis + PaddleOCR
      - DOCX / images     → converted through MinerU's converter chain

    Args:
        file_bytes: Raw file content
        filename:   Original filename (used for extension + output naming)

    Returns:
        (lc_docs, full_text, page_count)
        - lc_docs:    list of _ChunkDoc objects (same interface as Docling path)
        - full_text:  full markdown text of the document
        - page_count: number of pages detected
    """
    t0 = time.time()
    print(f"📄 MinerU: parsing {filename} ...")

    tmp_dir = tempfile.mkdtemp(prefix="mineru_")
    try:
        # ── 1. Run MinerU ──────────────────────────────────────────────
        full_text, content_list = _run_mineru(file_bytes, filename, tmp_dir)

        t_parse = time.time() - t0
        print(f"   MinerU parse done in {t_parse:.1f}s — "
              f"{len(full_text)} chars, {len(content_list)} content blocks")

        # ── 2. Extract page count ──────────────────────────────────────
        page_count = _count_pages_from_content_list(content_list)

        # ── 3. Chunk ───────────────────────────────────────────────────
        if content_list:
            lc_docs = _build_chunks_from_content_list(content_list)
        else:
            print("⚠️  MinerU: falling back to raw markdown chunker")
            lc_docs = _chunk_markdown_fallback(full_text)

        if not lc_docs:
            raise RuntimeError("No chunks produced from MinerU output")

        # ── 4. Sanitize NUL bytes (PostgreSQL rejects them in TEXT) ────
        full_text = full_text.replace("\x00", "")
        for doc in lc_docs:
            doc.page_content = doc.page_content.replace("\x00", "")

        t_total = time.time() - t0
        print(f"✅ MinerU: {page_count} pages | {len(lc_docs)} chunks | "
              f"{len(full_text)} chars | total {t_total:.1f}s")

        return lc_docs, full_text, page_count

    finally:
        # Always clean up MinerU temp output
        shutil.rmtree(tmp_dir, ignore_errors=True)
