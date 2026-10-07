# GridIntel API + web command center (single image). Private data and trained models are NOT baked in:
# mount them at DATA_ROOT / MODEL_PATH (the API trains models at startup if data/raw is present and models are missing).
# --- stage 1: browser build of the Expo field app (served at /mobile)
FROM node:22-slim AS mobile
WORKDIR /mobile
COPY mobile/package.json mobile/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY mobile/ ./
RUN CI=1 EXPO_OFFLINE=1 npx expo export --platform web --output-dir dist

# --- stage 2: API + web command center
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    APP_ENV=production DATA_ROOT=/data MODEL_PATH=/models REPORTS_DIR=/models/reports FRONTEND_DIR=/app/frontend
WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt
COPY ml/ ml/
COPY backend/ backend/
COPY frontend/ frontend/
COPY --from=mobile /mobile/dist/ mobile/dist/
COPY data/sources/ data/sources/
COPY scripts/ scripts/
COPY i18n/ i18n/
RUN useradd --create-home --uid 10001 gridintel && mkdir -p /data /models && chown -R gridintel /data /models /app
USER gridintel
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
WORKDIR /app/backend
CMD ["sh", "-c", "python -m alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
