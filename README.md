# LeadDiscovery

LeadDiscovery is a FastAPI + React application for discovering business leads by country, storing them in a deduplicated master database, tracking user credits, and exporting results for follow-up.

The intended deployment is:

- Backend: Render native Python web service
- Frontend: Vercel Vite static app
- Database: MongoDB Atlas or local MongoDB
- External API: Google Places API

Docker is not required for local testing or production deployment.

## Features

- Country and region business searches powered by Google Places.
- Automatic deduplication into the master database by country.
- Search history with completed, failed, and rate-limited states.
- User login, JWT auth, credit limits, and admin portal at `/admin`.
- Admin tools for users, passwords, credits, active status, and country cleanup.
- Excel and CSV exports with a `Source` column set to `LeadDiscovery`.
- Optional S3 export storage for production.

## Project Structure

```text
lead-discovery/
|-- backend/
|   |-- app/                 # FastAPI app
|   |-- scripts/             # maintenance scripts
|   |-- .env.example         # backend env template
|   |-- requirements.txt
|   |-- runtime.txt          # Render Python version
|   |-- run_backend.ps1      # Windows local launcher
|   `-- run_backend.bat
|-- frontend/
|   |-- src/                 # React app
|   |-- .env.example         # Vercel/local frontend env template
|   |-- package.json
|   `-- vercel.json          # SPA route fallback
|-- render.yaml              # Render native Python service blueprint
`-- README.md
```

## Local Setup Without Docker

Open PowerShell.

### 1. Clone and enter the project

```powershell
cd D:\tritorc\lead_dcy
git clone <your-git-repo-url> lead-discovery
cd lead-discovery
```

If the repo already exists:

```powershell
cd D:\tritorc\lead_dcy\lead-discovery
```

### 2. Create backend env file

```powershell
Copy-Item backend\.env.example backend\.env
notepad backend\.env
```

Set these values:

```env
GOOGLE_PLACES_API_KEY=your-google-places-api-key
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=lead_discovery
APP_SECRET_KEY=replace-with-a-long-random-secret

BOOTSTRAP_ADMIN_USERNAME=your-admin-email@example.com
BOOTSTRAP_ADMIN_PASSWORD=choose-a-strong-admin-password
BOOTSTRAP_ADMIN_CREDIT_LIMIT=1000

BOOTSTRAP_USER_USERNAME=test
BOOTSTRAP_USER_PASSWORD=choose-a-test-user-password
BOOTSTRAP_USER_CREDIT_LIMIT=1000

CORS_ALLOWED_ORIGINS=
```

Keep `backend\.env` private. Do not commit it.

### 3. Start MongoDB

Use either local MongoDB:

```powershell
mongod
```

Or set `MONGO_URI` in `backend\.env` to your MongoDB Atlas connection string.

### 4. Install and start the backend

```powershell
cd D:\tritorc\lead_dcy\lead-discovery\backend
python -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Or from the project root:

```powershell
cd D:\tritorc\lead_dcy\lead-discovery
.\backend\run_backend.ps1
```

Backend URLs:

- Health: `http://127.0.0.1:8000/health`
- API docs: `http://127.0.0.1:8000/docs`
- API base: `http://127.0.0.1:8000/api`

### 5. Install and start the frontend

Open a second PowerShell terminal:

```powershell
cd D:\tritorc\lead_dcy\lead-discovery\frontend
npm install
npm run dev
```

Open:

```text
http://localhost:5173
```

Local frontend development automatically uses:

```text
http://localhost:8000/api
```

### 6. Log in as admin

Use the values from:

```env
BOOTSTRAP_ADMIN_USERNAME
BOOTSTRAP_ADMIN_PASSWORD
```

Then open:

```text
http://localhost:5173/admin
```

Only users with role `admin` can see the admin portal.

## Deploy Backend To Render

This project is ready for Render without Docker.

### Option A: Use `render.yaml`

1. Push the repo to GitHub, GitLab, or Bitbucket.
2. In Render, choose **New +** -> **Blueprint**.
3. Connect the repo.
4. Render reads `render.yaml` and creates the backend service from `backend/`.
5. Add the secret environment variables listed below.

### Option B: Create a Web Service manually

Use these Render settings:

```text
Runtime: Python
Root Directory: backend
Build Command: pip install -r requirements.txt
Start Command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
Health Check Path: /health
```

Render environment variables:

```env
PYTHON_VERSION=3.12.8
GOOGLE_PLACES_API_KEY=your-google-places-api-key
MONGO_URI=your-mongodb-atlas-uri
MONGO_DB_NAME=lead_discovery
APP_SECRET_KEY=generate-a-long-random-secret

BOOTSTRAP_ADMIN_USERNAME=your-admin-email@example.com
BOOTSTRAP_ADMIN_PASSWORD=choose-a-strong-admin-password
BOOTSTRAP_ADMIN_CREDIT_LIMIT=1000

BOOTSTRAP_USER_USERNAME=test
BOOTSTRAP_USER_PASSWORD=choose-a-test-user-password
BOOTSTRAP_USER_CREDIT_LIMIT=1000

CORS_ALLOWED_ORIGINS=https://your-vercel-app.vercel.app
```

After deploy, test:

```text
https://your-render-service.onrender.com/health
```

## Deploy Frontend To Vercel

1. Push the same repo to GitHub, GitLab, or Bitbucket.
2. In Vercel, import the repo.
3. Set the project root directory to:

```text
frontend
```

4. Use the Vite defaults:

```text
Build Command: npm run build
Output Directory: dist
```

5. Add this Vercel environment variable:

```env
VITE_API_BASE=https://your-render-service.onrender.com/api
```

6. Deploy.

After Vercel gives you the frontend URL, go back to Render and set:

```env
CORS_ALLOWED_ORIGINS=https://your-vercel-app.vercel.app
```

Redeploy the Render backend after changing CORS.

## Production Notes

- Use MongoDB Atlas for Render. Localhost MongoDB will not work from Render.
- In MongoDB Atlas Network Access, allow Render to connect to the database.
- Keep `GOOGLE_PLACES_API_KEY`, `MONGO_URI`, `APP_SECRET_KEY`, and passwords out of Git.
- Render free services can sleep after inactivity, so the first request may be slow.
- Render's filesystem is ephemeral. For persistent export files, set `S3_BUCKET`, `S3_REGION`, and optionally `S3_PREFIX`.
- Vercel frontend environment variables are baked into the build, so redeploy Vercel after changing `VITE_API_BASE`.

## Useful Commands

Run backend checks:

```powershell
cd D:\tritorc\lead_dcy\lead-discovery\backend
.\venv\Scripts\python.exe -m compileall -q app scripts
.\venv\Scripts\python.exe -c "import app.main; print('backend import ok')"
```

Run frontend production build:

```powershell
cd D:\tritorc\lead_dcy\lead-discovery\frontend
npm run build
```

Check Git status before pushing:

```powershell
cd D:\tritorc\lead_dcy\lead-discovery
git status --short
```

Commit and push:

```powershell
git add .
git commit -m "Prepare Render and Vercel deployment"
git push
```

## Troubleshooting

### `.\backend\run_backend.ps1` says the path is missing

Run it from the project root:

```powershell
cd D:\tritorc\lead_dcy\lead-discovery
.\backend\run_backend.ps1
```

If you are already inside `backend`, use:

```powershell
.\run_backend.ps1
```

### Admin portal is missing

Log in with the bootstrap admin account. Normal users do not see `/admin`.

### Frontend says it cannot sign in

Check the backend health endpoint first:

```text
http://127.0.0.1:8000/health
```

For Vercel, confirm `VITE_API_BASE` ends with `/api` and points to the Render backend.

### Searches run forever

Open History. The backend cleans stale running searches when history is fetched. If the issue repeats, check the Render logs or local backend terminal for Google Places errors, rate limits, or MongoDB connection errors.

### Searches return very few businesses

Confirm the Google Places API key is valid, billing is enabled, and the selected country is supported by the configured search keywords.

## Deployment References

- Render web services require apps to bind to `0.0.0.0` and use the provided port.
- Vercel Vite apps read build-time frontend variables with the `VITE_` prefix.
