# Deploying InsightSQL with Docker

Three services run from `compose.yaml`:

| Service | What it does |
|---------|--------------|
| **app** | The Streamlit app. Checks its settings first and stops with a clear message if one must be fixed |
| **worker** | Scheduled dataset refreshes, and a daily backup (02:00 by default) |
| **proxy** | Caddy: the only part reachable from outside. HTTPS with a free certificate when you give it a domain name |

All data (databases and uploaded files) lives in the Docker volume `insightsql_data`. Backups go to
`./backups`.

## 1. First start (on your computer)

You need Docker with Compose (`docker compose version` should work).

```bash
cp .env.example .env          # skip if you already have a .env
mkdir -p backups
docker compose up -d --build
docker compose ps             # app should say "healthy"
```

Open **http://localhost**. Stop with `docker compose down` (your data stays).

## 2. On a server, with your own domain and HTTPS

1. Get a Linux server (any small VPS) with Docker installed, and a domain name.
2. Point the domain (for example `insights.example.com`) at the server's IP address (a DNS "A" record).
3. Open ports **80** and **443** in the server's firewall.
4. Copy the project to the server, then edit `.env` and add:

   ```bash
   SITE_ADDRESS=insights.example.com
   TZ=Europe/London                 # your time zone: the daily backup follows it
   INSIGHTSQL_SECRET_KEY=...        # see .env.example for the command that makes one
   ```

5. Turn on sign-in (step 3 below). **Do not run a public server with sign-in off.**
6. Start it:

   ```bash
   mkdir -p backups && sudo chown 1000:1000 backups   # the app runs as user 1000
   docker compose up -d --build
   ```

Caddy gets the HTTPS certificate by itself within a minute; open **https://insights.example.com**.

## 3. Sign-in (required on a public server)

1. Follow README → *User accounts* to create the Google or Microsoft sign-in app. Use
   `https://<your domain>/oauth2callback` as the redirect address.
2. `cp .streamlit/secrets.toml.example .streamlit/secrets.toml` and fill it in.
3. In `.env`:

   ```bash
   INSIGHTSQL_AUTH=oidc
   INSIGHTSQL_ADMIN_EMAILS=you@example.com
   COMPOSE_FILE=compose.yaml:compose.signin.yaml   # gives the app secrets.toml (read-only)
   ```

4. `docker compose up -d`

If something is missing, the app does not start; `docker compose logs app` says what to fix.

## 4. Everyday commands

| Task | Command |
|------|---------|
| Status | `docker compose ps` |
| Messages | `docker compose logs -f app` (or `worker`, `proxy`) |
| Update to new code | `git pull` then `docker compose up -d --build` |
| Stop / start | `docker compose down` / `docker compose up -d` |
| Backup now | `docker compose exec worker python scripts/backup.py create` |
| List backups | `docker compose exec worker python scripts/backup.py list` |

Never run `docker compose down -v`: `-v` **deletes the data volume**.

## 5. Restore a backup

```bash
docker compose stop app worker
docker compose run --rm --no-deps worker python scripts/backup.py list
docker compose run --rm --no-deps worker python scripts/backup.py restore 20261012-020000 --yes
docker compose start app worker
```

## 6. Production checklist

- [ ] `INSIGHTSQL_AUTH=oidc`, `INSIGHTSQL_ADMIN_EMAILS` set, `compose.signin.yaml` in `COMPOSE_FILE`
- [ ] `SITE_ADDRESS` is your domain, and the site opens with **https://**
- [ ] `INSIGHTSQL_SECRET_KEY` set, and **a copy kept somewhere other than the server** (backups do not contain it; without it, saved connection passwords cannot be read)
- [ ] `.env` and `.streamlit/secrets.toml` readable only by you (`chmod 600`), never committed
- [ ] `TZ` set; a backup appears in `./backups` the next day; **copy `./backups` off the server regularly**
- [ ] Restore tried once (section 5)
- [ ] Only ports 80 and 443 open

## Settings for Docker (in `.env`)

| Setting | Default | Meaning |
|---------|---------|---------|
| `SITE_ADDRESS` | `http://localhost` | Your domain name (HTTPS automatic) or `http://localhost` |
| `HTTP_PORT` / `HTTPS_PORT` | `80` / `443` | Ports on the server |
| `TZ` | `UTC` | Time zone for the backup schedule |
| `INSIGHTSQL_BACKUP_AT` | `02:00` | Daily backup time |
| `INSIGHTSQL_BACKUP_KEEP` | `7` | How many backups are kept |
| `BACKUP_DIR` | `./backups` | Backup folder on the server |

The data paths (`INSIGHTSQL_DB_PATH` …) are fixed inside the containers; those in `.env` are only
for running without Docker.
