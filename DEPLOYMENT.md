# Deployment Guide

This project is currently documented for a lightweight EC2 deployment.

## Production shape

```text
EC2 instance: t3.micro
OS: Ubuntu 24.04
Backend: FastAPI / Uvicorn, run as a Docker container
Image: ghcr.io/tritorc-ai1/lead-discovery-backend (built by GitHub Actions)
Backend bind: 127.0.0.1:8001
Process manager: Docker (restart: unless-stopped)
Reverse proxy: nginx on port 80
Database: MongoDB Atlas
Frontend: Vite React build served by nginx or separate static hosting (Vercel today)
```

## Automatic deploys (Docker + GitHub Actions)

Pushing to `master` (changes under `backend/`, `docker-compose.yml` or the workflow) runs
`.github/workflows/deploy-backend.yml`:

1. **build** - builds `backend/Dockerfile` and pushes `:latest` and `:<commit sha>` to GHCR.
   Pull requests only build the image (no push, no deploy).
2. **deploy** - copies `docker-compose.yml` to `/opt/lead-discovery/` on the EC2 host over SSH,
   pulls the new image, runs `docker compose up -d`, and fails the run if
   `http://127.0.0.1:8001/health` is not healthy within about 60 seconds.

The image is built in GitHub Actions, never on the server (the t3.micro has 1 GB RAM).
Secrets stay in `/opt/lead-discovery/.env` on the server and are passed in with `env_file`.
Exports are kept in `/opt/lead-discovery/exports` (mounted into the container).

### One-time setup

1. Allocate an Elastic IP and associate it with the instance, then add it to the Atlas
   Network Access list of the project that owns the cluster in `MONGO_URI`.
2. Run `deploy/deploy_docker_setup.sh` on the server (installs Docker, adds swap, creates dirs):

   ```bash
   scp -i <key>.pem deploy/deploy_docker_setup.sh ubuntu@<EIP>:~/
   ssh -i <key>.pem ubuntu@<EIP> "sudo bash ~/deploy_docker_setup.sh"
   ```

3. Add GitHub repository secrets: `EC2_HOST` (Elastic IP), `EC2_USER` (`ubuntu`),
   `EC2_SSH_KEY` (contents of the `.pem` key). The registry login uses the built-in
   `GITHUB_TOKEN`, so no extra token is needed.
4. Merge to `master`. The first deploy stops and disables `lead-discovery.service` and starts
   the container in its place.

### Rollback

```bash
# redeploy an older build
cd /opt/lead-discovery && IMAGE_TAG=<older-commit-sha> docker compose up -d

# or go back to the old systemd service
cd /opt/lead-discovery && docker compose down && sudo systemctl enable --now lead-discovery
```

Useful commands on the server:

```bash
docker compose ps
docker compose logs -f backend
```

The sections below describe the previous systemd setup and the values the app needs; the
environment variables apply to the container as well.

## Backend runtime

The backend service should run from the `backend/` directory with the project virtualenv installed.

Typical command:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

For local development, port `8000` is easier because the frontend currently defaults to `http://localhost:8000/api`.

If backend runs on `8001` locally, update frontend configuration:

```text
VITE_API_BASE=http://127.0.0.1:8001/api
```

or update `frontend/vite.config.js` proxy target to `http://127.0.0.1:8001`.

## Required backend environment variables

Set these in the backend `.env` or the systemd service environment:

```env
GOOGLE_PLACES_API_KEY=your-google-places-api-key
MONGO_URI=your-mongodb-atlas-uri
MONGO_DB_NAME=lead_discovery
APP_SECRET_KEY=generate-a-long-random-secret

BOOTSTRAP_ADMIN_USERNAME=admin@example.com
BOOTSTRAP_ADMIN_PASSWORD=choose-a-strong-password
BOOTSTRAP_ADMIN_CREDIT_LIMIT=1000

BOOTSTRAP_USER_USERNAME=test@example.com
BOOTSTRAP_USER_PASSWORD=choose-a-test-password
BOOTSTRAP_USER_CREDIT_LIMIT=1000

CORS_ALLOWED_ORIGINS=http://your-domain-or-ip

LLM_FALLBACK_ENABLED=false
LLM_FALLBACK_MIN_SCORE=40
LLM_FALLBACK_MAX_SCORE=69
LLM_FALLBACK_MAX_CALLS_PER_SEARCH=50
LLM_FALLBACK_MAX_CALLS_PER_MONTH=1000
```

Optional export storage:

```env
S3_BUCKET=
S3_REGION=
S3_PREFIX=exports/
```

## systemd service

Expected service name:

```text
lead-discovery.service
```

Useful commands:

```bash
sudo systemctl status lead-discovery.service
sudo systemctl restart lead-discovery.service
sudo journalctl -u lead-discovery.service -f
```

The service should start Uvicorn on:

```text
127.0.0.1:8001
```

## nginx

nginx should proxy API traffic to the backend:

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8001/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

If serving the frontend from nginx, build it first:

```bash
cd frontend
npm install
npm run build
```

Then point nginx root to the `frontend/dist` directory or copy `dist` into the configured web root.

## MongoDB Atlas

Production uses MongoDB Atlas.

Checklist:

- Atlas user exists.
- Atlas password is current.
- Atlas network access allows the EC2 server IP.
- `MONGO_URI` uses the correct database cluster.
- MongoDB DNS/SRV resolution works from the server.

If the backend fails during startup while creating indexes, check Atlas DNS/network access first.

## Google Places API quota

The app tracks Google Places usage in MongoDB:

```text
api_usage_monthly.place_details_calls
```

Current configured free limit:

```text
PLACE_DETAILS_MONTHLY_FREE_LIMIT = 1000
QUOTA_WARNING_THRESHOLD = 800
```

Important:

- Crawling websites does not consume Google Places quota.
- Google Places Text Search / details calls consume app credits.
- Broad searches can burn hundreds of credits quickly.
- The app blocks new searches when the monthly counter reaches 1000 and paid overage is off.

## Crawler capacity on t3.micro

Crawlee BeautifulSoup crawling is intentionally lightweight.

Keep defaults conservative:

```text
MAX_PAGES_PER_SITE = 5
CRAWLER_NAVIGATION_TIMEOUT_SECONDS = 10
max_crawl_depth = 1
max_request_retries = 1
```

Avoid Playwright/browser crawling on `t3.micro` unless it is a separate, controlled fallback job.

## Validation before deploy/restart

Backend:

```bash
cd backend
python -m compileall -q app scripts
python -c "import app.main; print('backend import ok')"
```

Frontend:

```bash
cd frontend
npm run build
```

## Latest crawler status

Active scoring:

```text
CRAWL_VERSION = tritorc-crawl-v3
SCORING_VERSION = role-concept-score-v1
```

The v3 crawler stores:

- crawl tier/score/status/reason
- detected language
- matched positive/negative concepts
- business role
- business-role signals and reason
- original evidence snippets and evidence URLs
- optional LLM fallback status fields

