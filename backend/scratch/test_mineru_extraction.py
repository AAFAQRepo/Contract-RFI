"""
MinerU extraction latency benchmark script.

Usage:
    python backend/scratch/test_mineru_extraction.py <path_to_pdf>

Prints:
    - MinerU parse time
    - Chunking time
    - Total time
    - Page count
    - Chunk count
    - First 3 chunk previews
"""

import os
import sys
import time

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_mineru_extraction.py <path_to_pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not os.path.exists(pdf_path):
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    with open(pdf_path, "rb") as f:
        file_bytes = f.read()

    filename = os.path.basename(pdf_path)
    print(f"\n{'='*60}")
    print(f"  MinerU Extraction Benchmark")
    print(f"  File: {filename}  ({len(file_bytes)/1024:.1f} KB)")
    print(f"{'='*60}\n")

    from services.extraction import extract_and_chunk

    t0 = time.time()
    lc_docs, full_text, page_count = extract_and_chunk(file_bytes, filename)
    t_total = time.time() - t0

    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")
    print(f"  Total time    : {t_total:.2f}s")
    print(f"  Pages         : {page_count}")
    print(f"  Chunks        : {len(lc_docs)}")
    print(f"  Full text len : {len(full_text)} chars")
    print(f"\n  --- First 3 chunks ---")
    for i, doc in enumerate(lc_docs[:3]):
        meta = doc.metadata.get("dl_meta", {})
        headings = meta.get("headings", [])
        doc_items = meta.get("doc_items", [])
        page = 0
        if doc_items:
            for item in doc_items:
                for prov in item.get("prov", []):
                    if prov.get("page_no", 0) > page:
                        page = prov["page_no"]
        print(f"\n  [{i+1}] Page {page} | Section: {headings[0] if headings else '—'}")
        preview = doc.page_content[:200].replace("\n", " ")
        print(f"       {preview}...")
    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
