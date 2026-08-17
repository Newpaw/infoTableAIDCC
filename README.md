# AIDCC Genesys rozcestník

Interní launcher pro koordinaci omezených Genesys Cloud licencí a analýzu jejich využití.

## Funkce

- vstup do **Produkce** (`https://login.mypurecloud.de`) a **Testu** (`https://login.mypurecloud.ie`)
- atomická rezervace licence v SQLite před přesměrováním
- ruční odhlášení
- persistentní SQLite databáze
- upozornění na dlouhé aktivní session
- analytická záložka s historií a statistikami

### Alerty

Výchozí nastavení: do 60 minut normální stav, 60–120 minut upozornění, nad 120 minut kritický alert. Alert je pouze vizuální; přihlášení se samo neuvolní.

### Statistiky

Záložka **Statistiky** obsahuje počet session a celkový čas využití, průměr a medián délky session, maximální počet současně aktivních session, porovnání PROD vs. TEST, přihlášení podle hodiny dne, denní využití, největší uživatele, dlouhá přihlášení a kompletní historii kdo/kam/kdy/na jak dlouho.

## Docker image

`ghcr.io/newpaw/infotableaidcc:latest`

## Portainer

- Container port: `8000`
- Persistent volume: `genesysinfotable-data` → `/app/data`
- `DATABASE_PATH=/app/data/tracker.db`
- `APP_BASE_PATH` není potřeba

## API

- `GET /api/status`
- `GET /api/analytics?days=30`
- `GET /api/history`
- `POST /api/enter`
- `POST /api/check-out`
- `GET /health`
