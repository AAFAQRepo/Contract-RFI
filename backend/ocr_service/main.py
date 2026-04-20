from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from typing import List
import tempfile
import os
import time
import threading
import traceback
from ocr_service.utils import ConverterRegistry

app = FastAPI(title="Contract RFI OCR Service")
gpu_lock = threading.Lock()

@app.get("/health")
def health():
    return {"status": "ok", "engine": "docling-surya"}

@app.post("/convert")
def convert(
    file: UploadFile = File(...),
    tier: str = Form("ocr")
):
    """
    Individual page conversion. Guarded by a lock to prevent CUDA collisions.
    """
    if tier not in ["lean", "enriched", "ocr"]:
        raise HTTPException(status_code=400, detail="Invalid tier")

    t_start = time.time()
    filename = file.filename or "document.pdf"
    
    suffix = os.path.splitext(filename)[1] or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = file.file.read() 
        tmp.write(content)
        tmp_path = tmp.name

    try:
        with gpu_lock:
            print(f"🚀 [OCR Service] Processing Single: {filename}")
            converter = ConverterRegistry.get(tier)
            result = converter.convert(tmp_path)
            doc_dict = result.document.export_to_dict()
            md = result.document.export_to_markdown()
            pages = len(result.document.pages) if hasattr(result.document, "pages") else 1
        
        latency = time.time() - t_start
        print(f"✅ [OCR Service] Finished Single {filename} in {latency:.2f}s")
        
        return {
            "document": doc_dict,
            "markdown": md,
            "page_count": pages,
            "latency": latency
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

@app.post("/convert_batch")
def convert_batch(
    files: List[UploadFile] = File(...),
    tier: str = Form("ocr")
):
    """
    Batch conversion. Uses Docling's convert_all for native GPU batching.
    """
    t_start = time.time()
    print(f"🚀 [OCR Service] Received Batch of {len(files)} files")
    
    tmp_paths = []
    try:
        for file in files:
            suffix = os.path.splitext(file.filename)[1] or ".pdf"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(file.file.read())
                tmp_paths.append(tmp.name)

        converter = ConverterRegistry.get(tier)
        
        # convert_all is internal-batching optimized
        t_conv_start = time.time()
        results = list(converter.convert_all(tmp_paths))
        t_conv_end = time.time()
        
        output = []
        for res in results:
            output.append({
                "document": res.document.export_to_dict(),
                "markdown": res.document.export_to_markdown(),
                "page_count": len(res.document.pages) if hasattr(res.document, "pages") else 1
            })

        latency = time.time() - t_start
        conv_latency = t_conv_end - t_conv_start
        print(f"✅ [OCR Service] Batch of {len(files)} finished in {latency:.2f}s (Conv: {conv_latency:.2f}s)")
        
        # Proactive VRAM cleanup
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            
        return {"results": output, "latency": latency, "core_conversion_latency": conv_latency}

    except Exception as e:
        traceback.print_exc()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        for p in tmp_paths:
            if os.path.exists(p):
                os.unlink(p)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
