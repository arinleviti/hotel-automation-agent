# One container for the whole demo (step 18): FastAPI serves the API AND the built React page.
# Built by Cloud Build (`gcloud run deploy --source .`), so Docker isn't needed on your machine
# (it is used locally only to test the image). Same pattern as the flight disruption assistant.
#
# WHAT HAPPENS when the image is built:
#   1. a Node container builds the page (npm run build -> frontend/dist: plain HTML, CSS, JS files)
#   2. a Python container installs the backend's packages exactly as pinned in uv.lock
#      (PyTorch from its CPU-only store: no GPU libraries, see backend/pyproject.toml)
#   3. Docling reads one real invoice, which downloads its layout / table / OCR models INTO the
#      image, so the first visitor doesn't wait for a download
#   4. the built page is copied next to the backend; uvicorn starts the API on Cloud Run's port
#
# The folders keep the repo's layout (/app/backend, /app/data, /app/frontend/dist), because the code
# finds data/ and the page relative to its own files (e.g. main_graph.py: parents[4] / "data").

# ---------- 1. Build the React page ----------
FROM node:22-slim AS page
WORKDIR /frontend
# Dependencies first: Docker keeps this step cached while only the code changes.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- 2. The Python backend ----------
FROM python:3.12-slim

# System libraries Docling's OCR and image handling (OpenCV) need on a slim Debian image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# uv, the same version as on Arin's machine (the tool that installs exactly what uv.lock pins).
COPY --from=ghcr.io/astral-sh/uv:0.12.20 /uv /usr/local/bin/uv
# UV_PYTHON_DOWNLOADS=never: use this image's Python 3.12; UV_COMPILE_BYTECODE: faster start;
# HF_HOME: where Docling's models are downloaded (inside the image, step 3).
ENV UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HF_HOME=/app/.cache/huggingface

WORKDIR /app/backend
# Dependencies first (cached while only the code changes); --no-dev: no pytest in production.
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project

# The code (with its prompts) and the hotel's data (emails, documents, templates, CSVs).
COPY backend/src ./src
COPY data /app/data
RUN uv sync --frozen --no-dev

# 3. Warm-up: read invoice #1 once, so Docling's models are downloaded now, into the image.
RUN .venv/bin/python -c "from pathlib import Path; from backoffice.rag.parsing import parse_bytes; \
parse_bytes('FRP-INV-2026-1184.pdf', Path('/app/data/invoices/FRP-INV-2026-1184.pdf').read_bytes())"

# 4. The built page, served by FastAPI (api/app.py mounts /app/frontend/dist).
COPY --from=page /frontend/dist /app/frontend/dist

# PORT: Cloud Run tells the container which port to listen on (8080 by default).
ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PORT=8080
CMD ["sh", "-c", "uvicorn backoffice.api.app:app --host 0.0.0.0 --port ${PORT}"]
