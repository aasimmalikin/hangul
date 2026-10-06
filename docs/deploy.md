# Deploying Hangul

One server runs everything behind HTTPS:

```
internet ──► Caddy (80/443, automatic HTTPS) ──► web (Next.js :3000) ──► api (FastAPI :8000)
                                                   │                         │
                         Meta & Dodo webhooks ─────┘          Postgres + Redis (hosted, or on this server)
```

Only Caddy is public. The web app calls the API on the internal network, and the
WhatsApp and Dodo webhooks arrive through the web app's relays
(`/api/whatsapp/webhook`, `/api/billing/webhook`).

Images are built by GitHub Actions (`.github/workflows/images.yml`) and pulled by the
server, because `next build` needs more memory than a 2 GB server has.

## 1. One-time: images

1. Push to `main` (or run **Actions → images → Run workflow**). It publishes
   `ghcr.io/<you>/hangul-api` and `ghcr.io/<you>/hangul-web`.
2. In GitHub → your profile → **Packages**, open each package → **Package settings** →
   make it **private** and note that the server needs a token to pull: create a
   **classic token** with only `read:packages`.

## 2. One-time: the server (AWS Lightsail, 2 GB, Mumbai)

1. Create a Lightsail instance: **Ubuntu 24.04**, the **2 GB** plan (4 GB if Postgres
   and Redis run on it too). Attach a **static IP**.
2. **Networking**: open TCP **80** and **443** (and UDP 443). Keep 22 for SSH.
3. Point your domain's **A record** (for example `app.example.com`) at the static IP.
4. SSH in and install Docker:
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER && newgrp docker
   ```
5. Add 2 GB of swap (a safety margin for memory spikes):
   ```bash
   sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
   ```
6. Get the deploy files (only these are needed on the server):
   ```bash
   git clone https://github.com/<you>/agentic-qa.git hangul && cd hangul
   echo <token> | docker login ghcr.io -u <you> --password-stdin
   ```
7. Settings: `cp .env.production.example .env.production` and fill it in. Required:
   `HANGUL_DOMAIN`, `APP_URL`, `DATABASE_URL`, `REDIS_URL`, `AUTH_PG_URL`, `JWT_SECRET`
   (= `FASTAPI_JWT_SECRET`), `VAULT_MASTER_KEY`, `AUTH_SECRET`, `AUTH_URL`, the Google
   sign-in keys, `OPENAI_API_KEY`, and **`BILLING_FREE_POOL_USD`** if billing is on.
   In the Google Cloud console, add `https://<domain>/api/auth/callback/google` as an
   authorised redirect URI.

## 3. Start it

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production pull
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
# with Postgres + Redis on this server instead of hosted ones:
docker compose -f docker-compose.prod.yml --env-file .env.production --profile db up -d
```

The API applies database migrations every time it starts (`start.sh`). Caddy gets the
certificate within a minute of the domain resolving.

**First time only**, index the shared documents into the database:

```bash
docker compose -f docker-compose.prod.yml exec api python -m harness.retrieval.ingest docs
```

Then check it: `scripts/smoke_test.sh https://<domain>`.

## 4. Update

```bash
git pull                                   # compose file / Caddyfile changes
docker compose -f docker-compose.prod.yml --env-file .env.production pull
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
scripts/smoke_test.sh https://<domain>
```

To roll back, set `HANGUL_IMAGE_TAG=<previous commit sha>` in `.env.production` and run
`up -d` again. (Migrations only move forward; check the release before rolling back
across one.)

## 5. Webhooks to register

| Service | URL |
|---|---|
| Dodo Payments | `https://<domain>/api/billing/webhook` |
| Meta (WhatsApp) | `https://<domain>/api/whatsapp/webhook`, verify token = `WHATSAPP_VERIFY_TOKEN` |

## Rules that matter

- **One API container.** The scheduler (reminders, tasks, the morning brief) runs inside
  it and isn't safe to run twice. Don't scale `api` past 1 or raise `WEB_CONCURRENCY`.
- **`BILLING_FREE_POOL_USD` set before launch.** It caps what all free users together can
  cost per month; the API logs a warning at startup when billing is on without it.
- **Backups.** Hosted Postgres (Neon) keeps its own history. With `--profile db`, turn on
  Lightsail automatic snapshots. The `data` volume holds users' files and the audit log.
- **Secrets** live only in `.env.production` on the server (and in the vault, encrypted
  with `VAULT_MASTER_KEY`). Losing `VAULT_MASTER_KEY` makes stored tokens unreadable.
- **Logs:** `docker compose -f docker-compose.prod.yml logs -f api web`.
