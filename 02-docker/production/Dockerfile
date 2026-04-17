# ============================================================
# ADVANCED Dockerfile — Multi-stage build
#
# Mục tiêu: image < 500 MB, secure, production-ready
#
# Tại sao multi-stage?
#   Stage 1 (builder): cần pip, gcc, build tools để compile deps
#   Stage 2 (runtime): chỉ cần Python và site-packages → nhỏ và sạch
# ============================================================

# ──────────────────────────────────────────────────────────
# STAGE 1: Builder
# Cài đặt tất cả dependencies
# Image này KHÔNG được dùng để deploy
# ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Cài build dependencies (cần cho một số packages như numpy)
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy và cài requirements
# Dùng --user để install vào /root/.local (dễ copy sang stage 2)
COPY 02-docker/develop/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# ──────────────────────────────────────────────────────────
# STAGE 2: Runtime
# Chỉ copy những gì cần để CHẠY, không cần để BUILD
# ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Tạo non-root user — security best practice
# Chạy với root trong container là bad practice
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Copy installed packages từ builder
COPY --from=builder /root/.local /home/appuser/.local

# Copy source code
COPY 02-docker/production/main.py .

# Copy utils from project root
RUN mkdir -p /app/utils
COPY utils/mock_llm.py /app/utils/mock_llm.py

# Đặt ownership cho appuser
RUN chown -R appuser:appuser /app

# Chuyển sang non-root user
USER appuser

# PATH để Python tìm được packages của --user install
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8000

# Health check — Docker sẽ tự restart nếu fail
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Start command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

# ============================================================
# Build commands (from project root):
#   cd ../../  # Go to project root
#   docker build -f 02-docker/production/Dockerfile -t agent-production .
#   docker images agent-production  ← kiểm tra size
#   docker run -p 8000:8000 -e ENVIRONMENT=production agent-production
# ============================================================
