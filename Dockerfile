FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for Playwright and other tools
RUN apt-get update && apt-get install -y \
    wget \
    curl \
    git \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium

# Create non-root user
RUN useradd -m -u 1000 jobhunter && \
    mkdir -p /app/data /app/logs /app/output && \
    chown -R jobhunter:jobhunter /app

USER jobhunter

# Copy application code
COPY --chown=jobhunter:jobhunter . .

# Create data directories
RUN mkdir -p data/naukri_profile logs/applications output

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

# Default command runs the main application
CMD ["python", "main.py"]
