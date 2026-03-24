# Genesys Cloud License Occupancy Tracker

Internal FastAPI utility for coordinating access to a limited pool of shared Genesys Cloud licenses.

## Features

- Shared Basic Authentication using environment variables
- Live dashboard showing occupied and free slots
- Check-in with employee name and optional note
- Check-out and force-release actions
- SQLite persistence for active sessions and history
- Stale-session highlighting with optional automatic release
- Docker and Docker Compose support

## Quick Start

1. Create a `.env` file from `.env.example`.
   Example: `cp .env.example .env`
2. Start the app with Docker Compose:

```bash
docker compose up --build
```

3. Open `http://localhost:8000/infotable/` when `APP_BASE_PATH=/infotable`, or `http://localhost:8000/` when the variable is empty.

## Run With Docker Only

Build the image:

```bash
docker build -t genesys-license-tracker .
```

Create a persistent volume for SQLite data:

```bash
docker volume create genesys-license-tracker-data
```

Run the container with your `.env` file:

```bash
docker run --rm \
  --name genesys-license-tracker \
  -p 8000:8000 \
  --env-file .env \
  -v genesys-license-tracker-data:/app/data \
  genesys-license-tracker
```

Then open `http://localhost:8000/infotable/` when `APP_BASE_PATH=/infotable`, or `http://localhost:8000/` when the variable is empty.

## Local Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload --env-file .env
```

If the app is hosted behind a shared URL path, set `APP_BASE_PATH` to that prefix, for example `/infotable`.

## Environment Variables

- `APP_USERNAME`
- `APP_PASSWORD`
- `APP_BASE_PATH` default empty string, example `/infotable`
- `MAX_SLOTS` default `5`
- `STALE_AFTER_MINUTES` default `480`
- `AUTO_RELEASE_STALE` default `false`
- `DATABASE_PATH` default `data/tracker.db`
- `HISTORY_LIMIT` default `20`

## Persistence

The SQLite database is stored under `/app/data/tracker.db` in the container and mounted through a Docker volume in `docker-compose.yml`.
