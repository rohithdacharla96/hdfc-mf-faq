# HDFC MF FAQ Assistant — production container.
# Runs on Hugging Face Spaces Docker (port 7860) and any container host
# that provides a PORT environment variable (Render, Railway, Fly, etc.).

FROM python:3.11-slim

# libgomp is needed by the CPU torch/onnxruntime wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Docker Spaces run the container as UID 1000.
RUN useradd -m -u 1000 user

ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/user/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/home/user/.cache/huggingface \
    TOKENIZERS_PARALLELISM=false \
    GROQ_MODEL=llama-3.3-70b-versatile

USER user
WORKDIR /home/user/app

COPY --chown=user requirements-deploy.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r requirements-deploy.txt

# Bake the embedding model into the image so the first request is fast.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# Application, prebuilt Chroma index, and UI.
COPY --chown=user . .

EXPOSE 7860

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
