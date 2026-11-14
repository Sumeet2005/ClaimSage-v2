FROM python:3.12-slim

# Install system dependencies: tesseract-ocr for scanned PDF OCR processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user and group
RUN groupadd -g 10001 claimsage && \
    useradd -u 10001 -g claimsage -s /bin/bash -m claimsage

WORKDIR /app

# Copy application manifest and source code
COPY pyproject.toml ./
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY scripts/ ./scripts/
COPY alembic.ini ./

# Install application and dependencies (using CPU-optimized torch to avoid unneeded ~3GB CUDA runtime wheels)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir .

# Set Hugging Face cache directory and pre-download embedding model to eliminate cold-start delay
ENV HF_HOME="/home/claimsage/.cache/huggingface"
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2', revision='1110a243fdf4706b3f48f1d95db1a4f5529b4d41')" && \
    chown -R claimsage:claimsage /home/claimsage/.cache

# Ensure application ownership
RUN chown -R claimsage:claimsage /app

# Switch to non-root user
USER claimsage

# Set runtime environment
ENV PYTHONPATH="/app/src:/app" \
    PYTHONUNBUFFERED="1" \
    CLAIMSAGE_DISABLE_DOTENV="1" \
    HF_HOME="/home/claimsage/.cache/huggingface"

EXPOSE 8000

# Default command runs the FastAPI application
CMD ["uvicorn", "claimsage.main:app", "--host", "0.0.0.0", "--port", "8000"]
