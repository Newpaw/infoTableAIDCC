# AIDCC Genesys rozcestník

Interní launcher pro koordinaci omezených Genesys Cloud licencí.

Uživatel zadá jméno a vybere **Produkci** nebo **Test**. Aplikace nejdřív atomicky rezervuje licenci v SQLite a až potom přesměruje do Genesysu.

- Produkce: `https://login.mypurecloud.de`
- Test: `https://login.mypurecloud.ie`
- výchozí bezpečnostní limit: 5 aktivních licencí celkem
- ruční odhlášení
- persistentní SQLite databáze
- aplikace běží přímo na `/`

## Docker image

Při pushi do `main` nebo `master` se image publikuje do:

```text
ghcr.io/newpaw/infotableaidcc:latest
```

## Docker Compose

```bash
cp .env.example .env
docker compose pull
docker compose up -d
```

Aplikace běží na `http://localhost:8000/`.

## Portainer

Doporučené nastavení při ručním vytvoření kontejneru:

- Image: `ghcr.io/newpaw/infotableaidcc:latest`
- Container port: `8000`
- Persistent volume: `genesysinfotable-data` → `/app/data`
- `DATABASE_PATH=/app/data/tracker.db`
- `APP_BASE_PATH` není potřeba

Image navíc deklaruje `VOLUME /app/data`. Pro snadnou správu a jistotu při redeployi je ale nejlepší explicitně připojit pojmenovaný volume `genesysinfotable-data`.

## URL a APP_BASE_PATH

Aplikace vždy obsluhuje hlavní stránku přímo na `/`.

Historický `APP_BASE_PATH=/infotable` už neřídí routing aplikace. Pokud proměnná zůstane v existujícím Portainer kontejneru nastavená, `/infotable` pouze přesměruje na `/`.

## Konfigurace

```env
APP_USERNAME=
APP_PASSWORD=
APP_BASE_PATH=
GLOBAL_MAX_SLOTS=5
PROD_URL=https://login.mypurecloud.de
PROD_MAX_SLOTS=5
TEST_URL=https://login.mypurecloud.ie
TEST_MAX_SLOTS=5
AUTO_RELEASE_STALE=false
STALE_AFTER_MINUTES=480
DATABASE_PATH=/app/data/tracker.db
HISTORY_LIMIT=30
```

`GLOBAL_MAX_SLOTS=5` je společná pojistka přes PROD i TEST. Pokud máte 5 licencí v každém prostředí zvlášť, nastav `GLOBAL_MAX_SLOTS=0`.

`AUTO_RELEASE_STALE=false` znamená, že se zapomenuté přihlášení samo neuvolní.

## Persistence

SQLite databáze je v `/app/data/tracker.db`. `docker-compose.yml` používá explicitně pojmenovaný volume `genesysinfotable-data:/app/data`, takže stav přežije restart i výměnu image.

## API

- `GET /api/status`
- `POST /api/enter`
- `POST /api/check-out`
- `GET /api/history`
- `GET /health`
