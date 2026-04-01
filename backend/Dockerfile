# Use NVIDIA PyTorch as base image for GPU performance
FROM pytorch/pytorch:2.2.0-cuda12.1-cudnn8-runtime

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PYTHONPATH=/app

WORKDIR /app

# Install system dependencies for PDF/OCR and Docling
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libgl1-mesa-glx \
    libglib2.0-0 \
    poppler-utils \
    tesseract-ocr \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose FastAPI port
EXPOSE 8000

# Default command (will be overridden in docker-compose for workers)
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
