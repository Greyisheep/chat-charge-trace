# Oja Connect backend: FastAPI + google-adk agent behind uvicorn.
#
# No .env is copied into the image on purpose. All configuration arrives
# through the container environment (docker compose passes the repo-root
# .env via env_file), so the image itself carries zero secrets.

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so source edits do not bust the pip layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user; nothing in the app needs root.
RUN useradd --create-home --shell /usr/sbin/nologin appuser
USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
