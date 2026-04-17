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

# ── MinerU must read MINERU_MODEL_SOURCE before package-level init ──────
# Pull from env (set in .env → loaded by the settings object) so the var
# is present when mineru internals import at function-call time.
os.environ.setdefault("MINERU_MODEL_SOURCE", "local")

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

def _run_mineru(
    file_bytes: bytes,
    filename: str,
    tmp_dir: str,
) -> tuple[str, list[dict]]:
    """
    Write file to tmp_dir, run MinerU do_parse, and return
    (markdown_text, content_list).

    MinerU writes output under:
        <tmp_dir>/<stem>/<stem>.md
        <tmp_dir>/<stem>/content_list.json
    """
    from mineru.cli.common import do_parse

    stem = Path(filename).stem or "document"
    ext = Path(filename).suffix.lower() or ".pdf"
    input_path = os.path.join(tmp_dir, f"{stem}{ext}")

    with open(input_path, "wb") as f:
        f.write(file_bytes)

    # Build safe basename for MinerU output naming
    safe_stem = stem[:80]  # avoid overly long paths

    do_parse(
        output_dir=tmp_dir,
        pdf_file_names=[safe_stem],
        pdf_bytes_list=[file_bytes],
        p_lang_list=["auto"],       # language auto-detect
        backend="pipeline",         # CPU-safe; set to "vlm-transformers" for GPU
        parse_method="auto",        # auto selects txt-extract vs OCR per page
        f_dump_md=True,
        f_dump_content_list=True,
        f_dump_middle_json=False,
        f_dump_model_json=False,
        f_dump_orig_pdf=False,
        f_draw_layout_bbox=False,
        f_draw_span_bbox=False,
    )

    # ── Locate output files ────────────────────────────────────────────
    # MinerU creates: <output_dir>/<safe_stem>/<safe_stem>.md
    doc_dir = os.path.join(tmp_dir, safe_stem)

    md_path = os.path.join(doc_dir, f"{safe_stem}.md")
    cl_path = os.path.join(doc_dir, "content_list.json")

    # Fallback: search recursively if naming differs between versions
    if not os.path.exists(md_path):
        for root, _, files in os.walk(tmp_dir):
            for fname in files:
                if fname.endswith(".md"):
                    md_path = os.path.join(root, fname)
                    break

    if not os.path.exists(cl_path):
        for root, _, files in os.walk(tmp_dir):
            for fname in files:
                if fname == "content_list.json":
                    cl_path = os.path.join(root, fname)
                    break

    # Read markdown
    markdown = ""
    if os.path.exists(md_path):
        with open(md_path, "r", encoding="utf-8") as f:
            markdown = f.read()
    else:
        print("⚠️  MinerU: markdown output file not found; using empty text")

    # Read content_list
    content_list: list[dict] = []
    if os.path.exists(cl_path):
        with open(cl_path, "r", encoding="utf-8") as f:
            content_list = json.load(f)
    else:
        print("⚠️  MinerU: content_list.json not found; chunking will fall back to raw markdown split")

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

        t_total = time.time() - t0
        print(f"✅ MinerU: {page_count} pages | {len(lc_docs)} chunks | "
              f"{len(full_text)} chars | total {t_total:.1f}s")

        return lc_docs, full_text, page_count

    finally:
        # Always clean up MinerU temp output
        shutil.rmtree(tmp_dir, ignore_errors=True)
