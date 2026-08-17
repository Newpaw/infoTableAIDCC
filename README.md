# AIDCC Genesys rozcestník

Jednoduchá interní webová aplikace pro hlídání omezených Genesys Cloud licencí.

Uživatel zadá své jméno a klikne na **Produkci** nebo **Test**. Aplikace atomicky zapíše obsazenou licenci do SQLite a až potom vrátí URL pro přesměrování do příslušného Genesys prostředí.

- Produkce: `https://login.mypurecloud.de`
- Test: `https://login.mypurecloud.ie`
- výchozí bezpečnostní limit: 5 licencí celkem přes obě prostředí
- zároveň lze nastavit samostatný limit pro PROD a TEST
- odhlášení je ruční
- zapomenuté přihlášení zůstává viditelné, dokud ho někdo neuvolní
- přehled se automaticky obnovuje každých 10 sekund

## Docker

Image se při pushi do `main` nebo `master` automaticky publikuje do:

```text
ghcr.io/newpaw/infotableaidcc:latest
```

### Docker Compose

```bash
cp .env.example .env
docker compose pull
docker compose up -d
```

Aplikace pak běží na `http://localhost:8000`.

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
DATABASE_PATH=data/tracker.db
HISTORY_LIMIT=30
```

`APP_USERNAME` a `APP_PASSWORD` jsou volitelné. Pokud je aplikace chráněná například přes Cloudflare Access, mohou zůstat prázdné. Pokud použiješ Basic Auth, musí být vyplněné oba údaje.

`GLOBAL_MAX_SLOTS=5` je celková pojistka přes PROD i TEST. Pokud máte ve skutečnosti 5 licencí v každém prostředí zvlášť, nastav `GLOBAL_MAX_SLOTS=0`.

`AUTO_RELEASE_STALE` nech standardně `false`. Tím se záznam nikdy sám neuvolní jen proto, že je starý.

## Persistence

SQLite databáze je v `/app/data/tracker.db`. `docker-compose.yml` používá persistentní volume `tracker-data`, takže stav přežije restart i výměnu image.

## API

- `GET /api/status` – aktuální obsazenost obou prostředí
- `POST /api/enter` – rezervace licence před přesměrováním
- `POST /api/check-out` – ruční uvolnění licence
- `GET /api/history` – poslední aktivita
- `GET /health` – healthcheck
