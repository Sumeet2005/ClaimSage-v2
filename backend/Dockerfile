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

# Ensure application ownership
RUN chown -R claimsage:claimsage /app

# Switch to non-root user
USER claimsage

# Set runtime environment
ENV PYTHONPATH="/app/src:/app" \
    PYTHONUNBUFFERED="1" \
    CLAIMSAGE_DISABLE_DOTENV="1"

EXPOSE 8000

# Default command runs the FastAPI application
CMD ["uvicorn", "claimsage.main:app", "--host", "0.0.0.0", "--port", "8000"]
