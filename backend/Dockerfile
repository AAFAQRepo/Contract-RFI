# Use CUDA 12.6 on Ubuntu 24.04
FROM nvidia/cuda:12.6.3-runtime-ubuntu24.04

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PYTHONPATH=/app
# Define the virtual environment path
ENV VIRTUAL_ENV=/opt/venv

WORKDIR /app

# Install Python 3.12 and system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3-pip \
    python3-dev \
    python3-venv \
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

# Create and activate virtual environment
RUN python3.12 -m venv $VIRTUAL_ENV
# Add venv to PATH so 'python' and 'pip' use it automatically
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Upgrade pip inside the venv
RUN pip install --no-cache-dir --upgrade pip

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
