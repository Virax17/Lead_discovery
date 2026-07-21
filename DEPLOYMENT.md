# Deployment Guide: Render + Vercel

This project is intended to deploy from Git without Docker:

- Render runs the FastAPI backend from `backend/`.
- Vercel builds and serves the Vite React frontend from `frontend/`.
- MongoDB Atlas stores production data.

## 1. Prepare Git

```powershell
cd D:\tritorc\lead_dcy\lead-discovery
git status --short
git add .
git commit -m "Prepare Render and Vercel deployment"
git push
```

Do not commit real `.env` files. The repo includes `.env.example` files only.

## 2. Backend On Render

Use the included `render.yaml` as a Render Blueprint, or create a Web Service manually with these settings:

```text
Runtime: Python
Root Directory: backend
Build Command: pip install -r requirements.txt
Start Command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
Health Check Path: /health
```

Required Render environment variables:

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

After deploy, check:

```text
https://your-render-service.onrender.com/health
```

## 3. Frontend On Vercel

Import the same Git repo into Vercel.

Use these Vercel settings:

```text
Root Directory: frontend
Framework Preset: Vite
Build Command: npm run build
Output Directory: dist
```

Required Vercel environment variable:

```env
VITE_API_BASE=https://your-render-service.onrender.com/api
```

Redeploy Vercel after changing `VITE_API_BASE`.

## 4. Connect CORS

When Vercel gives you the final app URL, set the backend Render variable:

```env
CORS_ALLOWED_ORIGINS=https://your-vercel-app.vercel.app
```

If you have both a preview domain and a custom domain, comma-separate them:

```env
CORS_ALLOWED_ORIGINS=https://lead-discovery.vercel.app,https://www.yourdomain.com
```

Redeploy the Render backend after changing CORS.

## 5. MongoDB Atlas

Render cannot use your local `mongodb://localhost:27017` database.

For production:

1. Create a MongoDB Atlas cluster.
2. Create a database user.
3. Put the Atlas connection string in Render as `MONGO_URI`.
4. Allow Render to connect in Atlas Network Access.

## 6. Export Storage

Without S3, generated exports are written to Render's local filesystem. That is fine for short-lived downloads, but Render's filesystem is ephemeral.

For durable production exports, set:

```env
S3_BUCKET=your-bucket-name
S3_REGION=us-east-1
S3_PREFIX=exports/
```

The AWS credentials available to Render must allow `s3:PutObject`, `s3:GetObject`, and `s3:HeadObject` for the bucket/prefix.

## 7. Local Smoke Test Before Deploy

Backend:

```powershell
cd D:\tritorc\lead_dcy\lead-discovery\backend
.\venv\Scripts\python.exe -m compileall -q app scripts
.\venv\Scripts\python.exe -c "import app.main; print('backend import ok')"
```

Frontend:

```powershell
cd D:\tritorc\lead_dcy\lead-discovery\frontend
npm run build
```

## 8. If Secrets Were Ever Committed

Rotate them before production:

- Google Places API key
- MongoDB Atlas password
- `APP_SECRET_KEY`
- Bootstrap admin and test-user passwords

Deleting a secret from the current working tree does not remove it from Git history.
