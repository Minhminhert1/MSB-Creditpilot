# ==============================================================================
# MSB Credit Proposal Copilot - GreenNode AgentBase Custom Agent Dockerfile
# ==============================================================================
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    APP_MODE=hackathon

# Install OS runtime dependencies required for PDFium, PDF processing, and network certs
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first for caching efficiency
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source, templates, and runtime assets
COPY . /app

# Ensure runtime directories exist
RUN mkdir -p /app/uploads /app/output

# AgentBase official exposed port
EXPOSE 8080

# Health check contract
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Official deterministic competition entrypoint
CMD ["python", "main.py"]
