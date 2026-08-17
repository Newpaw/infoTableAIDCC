FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/app/data/tracker.db

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY app /app/app

RUN pip install --no-cache-dir . \
    && mkdir -p /app/data \
    && python -m compileall -q /app/app \
    && DATABASE_PATH=/tmp/build-smoke.db python -c "from app.main import app; print(app.title)"

VOLUME ["/app/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
