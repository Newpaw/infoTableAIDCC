# AIDCC Control Center

Small operating cockpit for AIDCC projects and AI Voice outbound campaigns.

The MVP intentionally does **not** try to replace Jira, Confluence or analytics platforms. It answers four operational questions:

1. What is running?
2. What blocks launch or delivery?
3. Who owns the next action?
4. Which decision is still missing?

## MVP features

- Portfolio dashboard with health, blockers, overdue actions and upcoming launches
- Project detail with Business Owner and AIDCC SPOC
- Standard launch-readiness pipeline
- Actions with owner, status, due date, next action and go-live blocker flag
- Explicit decision log with AIDCC recommendation and final decision
- `Needs attention` queue
- Activity history
- Weekly update generator (Markdown)
- Import of the legacy AIDCC `.xlsx` workbook into SQLite
- SQLite persistence
- Optional HTTP Basic Auth
- Docker image, no Node build and no external database

## Run with one Docker command

The only thing that should be persisted is `/app/data`:

```bash
docker run -d \
  --name aidcc-control-center \
  --restart unless-stopped \
  -p 8000:8000 \
  -v aidcc-control-center-data:/app/data \
  ghcr.io/newpaw/aidcc-control-center:latest
```

Open `http://localhost:8000`.

### Optional authentication

No `.env` file is required. If the service is reachable outside a trusted network, set two variables:

```bash
docker run -d \
  --name aidcc-control-center \
  --restart unless-stopped \
  -p 8000:8000 \
  -e APP_USERNAME=aidcc \
  -e APP_PASSWORD='change-me' \
  -v aidcc-control-center-data:/app/data \
  ghcr.io/newpaw/aidcc-control-center:latest
```

## Import the current Excel board

Use **Import Excel** in the top navigation and upload the current AIDCC workbook. The file is processed by the application and stored in SQLite; it is not copied to the repository or image.

The importer understands:

- the `Status` readiness matrix
- campaign sheets with columns such as `task`, `detail`, `status`, `owner`, `date`, `next action/detail`
- Business Owner and AIDCC SPOC metadata where present
- cross-cutting sheets as `Enabler` projects

Re-importing replaces previously imported actions for the same sheet while preserving manually created actions.

## Local build

```bash
docker build -t aidcc-control-center .
docker run --rm -p 8000:8000 -v aidcc-control-center-data:/app/data aidcc-control-center
```

## Minimal configuration

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `APP_USERNAME` | No | empty | Enables Basic Auth when both auth variables are set |
| `APP_PASSWORD` | No | empty | Enables Basic Auth when both auth variables are set |
| `DATABASE_PATH` | No | `/app/data/aidcc.db` | Override SQLite location if needed |

## Data safety

Do not commit real AIDCC Excel files or SQLite databases. Both `*.xlsx` and `data/` are ignored by Git.

The repository contains only fictional demo records. Real internal data should enter through the running application and stay in its persistent volume.
