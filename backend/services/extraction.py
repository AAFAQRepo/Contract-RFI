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
from loguru import logger

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


def _ensure_str(val) -> str:
    """Helper to ensure we have a string, joining lists if necessary."""
    if val is None:
        return ""
    if isinstance(val, list):
        return " ".join(str(i) for i in val)
    return str(val)


def _heading_from_block(block: dict) -> str:
    """Return the text if this block is a header/title."""
    btype = block.get("type", "")
    if btype in ("title", "header", "header_text"):
        # MinerU v1 uses 'text', v2 uses 'content'
        text = block.get("text") or block.get("content")
        return _ensure_str(text).strip()
    
    # Check for text_level in v1
    if block.get("text_level"):
        return _ensure_str(block.get("text")).strip()
        
    return ""


def _page_from_block(block: dict) -> int:
    """Extract page number from block metadata."""
    # MinerU content_list uses 'page_id' (0-based) or 'page_no' (1-based)
    page_id = block.get("page_id")
    if page_id is not None:
        try:
            return int(_ensure_str(page_id)) + 1
        except: pass
        
    page_no = block.get("page_no")
    if page_no is not None:
        try:
            return int(_ensure_str(page_no))
        except: pass
        
    return 0


def _block_text(block: dict) -> str:
    """Get the rendered text of a content block."""
    btype = block.get("type", "")
    
    # Tables: Combine caption and body
    if btype == "table":
        caption = _ensure_str(block.get("table_caption"))
        body = _ensure_str(block.get("table_body"))
        return f"{caption}\n{body}".strip()
        
    # Images/Charts: Use caption only
    if btype in ("image", "figure", "chart"):
        return _ensure_str(block.get("img_caption") or block.get("chart_caption")).strip()
        
    # Standard text
    text = block.get("text") or block.get("content")
    return _ensure_str(text).strip()


def _recursive_split_text(text: str, max_words: int, overlap_words: int) -> list[str]:
    """
    Simple recursive text splitter that tries to split on paragraphs, then sentences.
    """
    if _estimate_words(text) <= max_words:
        return [text]

    # Try paragraphs
    blocks = text.split("\n\n")
    if len(blocks) > 1:
        chunks = []
        current = ""
        for b in blocks:
            if _estimate_words(current + "\n\n" + b) <= max_words:
                current = (current + "\n\n" + b).strip()
            else:
                if current: chunks.append(current)
                # If a single block is too big, recurse on it
                if _estimate_words(b) > max_words:
                    chunks.extend(_recursive_split_text(b, max_words, overlap_words))
                    current = ""
                else:
                    current = b
        if current: chunks.append(current)
        return chunks

    # Fallback: simple word split (could be improved with sentence splitting)
    words = text.split()
    chunks = []
    step = max_words - overlap_words
    for i in range(0, len(words), step):
        chunk = " ".join(words[i : i + max_words])
        if chunk.strip():
            chunks.append(chunk)
    return chunks


def _build_chunks_from_content_list(
    content_list: list[dict],
) -> list[_ChunkDoc]:
    """
    Convert MinerU's content_list into _ChunkDoc objects using a 
    recursive section-aware strategy.
    """
    sections: list[dict] = []
    current_section = {"heading": "", "page": 0, "blocks": []}

    for block in content_list:
        heading = _heading_from_block(block)
        page = _page_from_block(block)
        
        if heading:
            if current_section["blocks"]:
                sections.append(current_section)
            current_section = {"heading": heading, "page": page, "blocks": []}
            continue
        
        current_section["blocks"].append(block)
        if not current_section["page"]:
            current_section["page"] = page

    if current_section["blocks"]:
        sections.append(current_section)

    chunks: list[_ChunkDoc] = []
    
    # Process each section independently
    for sec in sections:
        heading = sec["heading"]
        page = sec["page"]
        
        # Combine blocks within the section
        section_text = "\n\n".join(_block_text(b) for b in sec["blocks"] if _block_text(b))
        if not section_text.strip():
            continue
            
        # Add heading to the text for context
        full_sec_text = f"## {heading}\n\n{section_text}" if heading else section_text
        
        # Split recursively
        splits = _recursive_split_text(full_sec_text, _MAX_WORDS, overlap_words=50)
        
        for split in splits:
            chunks.append(
                _ChunkDoc(
                    page_content=split,
                    metadata={
                        "dl_meta": {
                            "headings": [heading] if heading else [],
                            "doc_items": [{"prov": [{"page_no": page}]}],
                        }
                    },
                )
            )

    return chunks


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
    # Tune MinerU for high-fidelity throughput (22GB GPU safe)
    os.environ["MINERU_PROCESSING_WINDOW_SIZE"] = "256"

    # If it's a digital PDF, we force parse_method="txt" and disable heavy models.
    parse_method = "auto"
    if _is_text_native_pdf(file_bytes, ext):
        parse_method = "txt"
        os.environ["MINERU_FORMULA_ENABLE"] = "false"
        os.environ["MINERU_LAYOUT_ENABLE"] = "false"
        os.environ["MINERU_TABLE_ENABLE"] = "false"
        print("⚡ Text-native PDF detected. High-speed 'txt' path enabled (MFR/Layout/Table disabled).")

        from mineru.cli.common import do_parse
        import mineru.utils.pdf_image_tools as pdf_tools
        from mineru.backend.pipeline.batch_analyze import BatchAnalyze
        
        # ── Sub-100s Boost: Deep Monkey-Patch ─────────────────────────────
        # For digital PDFs, we force the Batch Controller to skip OCR detection stages
        # even if those flags are ignored by the high-level do_parse API.
        original_dpi = pdf_tools.DEFAULT_PDF_IMAGE_DPI
        
        pdf_tools.DEFAULT_PDF_IMAGE_DPI = 72
        
        # 2. Suppress Vision-OCR detection (Stage 1 boost)
        try:
            from mineru.backend.pipeline.batch_analyze import BatchAnalyze
            BatchAnalyze.__original_init__ = BatchAnalyze.__init__
            def patched_analyze_init(self, *args, **kwargs):
                self.__original_init__(*args, **kwargs)
                logger.warning("🚫 Deep-Patch: Suppressed Vision-OCR detection.")
                self.text_ocr_det_batch_enabled = False
            BatchAnalyze.__init__ = patched_analyze_init
        except Exception as e:
            logger.warning(f"⚠️ Could not patch BatchAnalyze: {e}")

        # 3. Suppress Post-Processor OCR (Stage 1 boost)
        try:
            import mineru.backend.pipeline.model_json_to_middle_json as mj
            def patched_apply_post_ocr(pdf_info_list, lang=None):
                logger.warning("🚫 Deep-Patch: Bypassing Post-Processor OCR.")
                return
            mj._apply_post_ocr = patched_apply_post_ocr
            
            # 4. Suppress Image/Table Cutting (I/O bypass)
            def patched_cut_image(span, *args, **kwargs):
                return span
            mj.cut_image_and_table = patched_cut_image
        except Exception as e:
            logger.warning(f"⚠️ Could not patch ModelJsonToMiddleJson: {e}")

        # 5. Extract and cleanup
        logger.warning("⚡ Sub-100s Boost: Lowering rendering DPI to 72 + Vision-OCR Suppression.")

        try:
            do_parse(
                output_dir=tmp_dir,
                pdf_file_names=[safe_stem],
                pdf_bytes_list=[file_bytes],
                p_lang_list=["en"],
                backend="pipeline",
                parse_method=parse_method,
                formula_enable=False if parse_method == "txt" else True,
                table_enable=False if parse_method == "txt" else True,
                f_dump_md=True,
                f_dump_content_list=True,
                f_dump_middle_json=False,
                f_dump_model_json=False,
                f_dump_orig_pdf=False,
                f_draw_layout_bbox=False,
                f_draw_span_bbox=False,
            )
        finally:
            # Restore original state
            pdf_tools.DEFAULT_PDF_IMAGE_DPI = original_dpi
            BatchAnalyze.__init__ = original_init

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
    
    # Find the best content_list.json
    # We prefer the standard format (v1) over v2 because our structural chunker 
    # is optimized for its flat block structure.
    cl_files = sorted(search_root.rglob("*content_list*.json"), key=lambda p: ("_v2" in p.name, p.name))
    if cl_files:
        cl_path = str(cl_files[0])

    # Read markdown
    markdown = ""
    if md_path and os.path.exists(md_path):
        with open(md_path, "r", encoding="utf-8") as f:
            markdown = f.read()

    # Read content list
    content_list = []
    if cl_path and os.path.exists(cl_path):
        with open(cl_path, "r", encoding="utf-8") as f:
            raw_cl = json.load(f)
            # NESTING GUARD: MinerU 3.0 v2 returns a list of lists (pages).
            # We flatten it to a single list of blocks for our chunker.
            if isinstance(raw_cl, list) and len(raw_cl) > 0 and isinstance(raw_cl[0], list):
                logger.warning("📦 Stage 1: Flattening nested MinerU 3.0 content_list.")
                for page in raw_cl:
                    content_list.extend(page)
            else:
                content_list = raw_cl
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
# Public API (Decoupled Stage 1 & 2)
# ─────────────────────────────────────────────────────────────────────────

def parse_only(
    file_bytes: bytes,
    filename: str,
) -> tuple[str, list[dict]]:
    """
    Stage 1: Run MinerU and return raw Markdown and ContentList. 
    Does NOT perform chunking.
    """
    tmp_dir = tempfile.mkdtemp(prefix="mineru_parse_")
    try:
        full_text, content_list = _run_mineru(file_bytes, filename, tmp_dir)
        return full_text, content_list
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def chunk_from_results(
    content_list: list[dict],
    full_text: str,
) -> tuple[list, int]:
    """
    Stage 2: Convert parsed outcomes into semantic chunks.
    """
    # 1. Derive page count
    page_count = _count_pages_from_content_list(content_list)

    # 2. Chunk
    if content_list:
        lc_docs = _build_chunks_from_content_list(content_list)
    else:
        lc_docs = _chunk_markdown_fallback(full_text)

    # 3. Sanitize NUL bytes
    for doc in lc_docs:
        doc.page_content = doc.page_content.replace("\x00", "")

    return lc_docs, page_count


def extract_and_chunk(
    file_bytes: bytes,
    filename: str,
) -> tuple[list, str, int]:
    """
    Legacy wrapper for synchronous extraction + chunking.
    """
    full_text, content_list = parse_only(file_bytes, filename)
    lc_docs, page_count = chunk_from_results(content_list, full_text)
    return lc_docs, full_text, page_count
