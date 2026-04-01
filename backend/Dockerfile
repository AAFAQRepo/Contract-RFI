# Use CUDA 12.6 on Ubuntu 24.04
FROM nvidia/cuda:12.6.3-runtime-ubuntu24.04

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PYTHONPATH=/app
# Allow pip to install packages globally in the container (Ubuntu 24.04 requirement)
ENV PIP_BREAK_SYSTEM_PACKAGES=1

WORKDIR /app

# Install Python 3.12 and system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3-pip \
    python3-dev \
    build-essential \
    curl \
    libgl1 \
    libglib2.0-0 \
    poppler-utils \
    tesseract-ocr \
    ffmpeg \
    git \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Ensure 'python' and 'pip' point to python3.12
RUN ln -s /usr/bin/python3.12 /usr/bin/python && \
    ln -s /usr/bin/pip3 /usr/bin/pip

# Install PyTorch specifically for CUDA 12.4+
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

# Install the rest of the requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose FastAPI port
EXPOSE 8000

# Default command
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
