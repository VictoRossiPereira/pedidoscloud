# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Usuário não-root (segurança)
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

WORKDIR /app

# Copiar dependências do builder
COPY --from=builder /install /usr/local

# Copiar código
COPY src/ .

# Remover utilitários desnecessários
RUN apt-get purge -y --auto-remove \
 && rm -rf /var/lib/apt/lists/* /tmp/* /root/.cache

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
