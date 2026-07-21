import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime
from app.config.settings import settings as app_settings
from app.db.connection import get_db
from app.db.indexes import ensure_indexes
from app.services.cleanup import run_export_cleanup_loop, sweep_expired_exports
from app.services.search_recovery import mark_stale_running_searches
from app.services.country_maintenance import normalize_all_countries
from app.services.users import seed_bootstrap_users

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await ensure_indexes()
    db = get_db()
    existing_settings = await db.app_settings.find_one({"_id": "singleton"})
    if not existing_settings:
        await db.app_settings.insert_one({
            "_id": "singleton",
            "active_plan": "free",
            "allow_paid_overage": False,
            "updated_at": datetime.utcnow(),
        })

    await seed_bootstrap_users()
    await mark_stale_running_searches()
    await normalize_all_countries(db)
    sweep_expired_exports()
    cleanup_task = asyncio.create_task(run_export_cleanup_loop())

    yield

    # Shutdown
    cleanup_task.cancel()

# Initialize FastAPI app
app = FastAPI(
    title="Lead Discovery API",
    description="Backend for the Lead Discovery Automation Platform",
    version="1.0.0",
    lifespan=lifespan
)

from app.api import auth, searches, quota, settings, countries, businesses, admin

# Setup CORS
configured_origins = [origin.strip() for origin in app_settings.cors_allowed_origins.split(",") if origin.strip()]

if configured_origins:
    # Production: only the explicitly configured origin(s) are allowed.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=configured_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    # Local dev default: Vite dev server on localhost/127.0.0.1, any port.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth.router, prefix="/api")
app.include_router(searches.router, prefix="/api")
app.include_router(quota.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(countries.router, prefix="/api")
app.include_router(businesses.router, prefix="/api")
app.include_router(admin.router, prefix="/api")

@app.get("/")
async def root():
    return {
        "message": "Lead Discovery API is running",
        "docs": "/docs",
        "api_root": "/api",
    }


@app.get("/api")
async def api_root():
    return {
        "message": "Lead Discovery API",
        "docs": "/docs",
        "health": "/health",
        "endpoints": [
            "/api/auth/login",
            "/api/searches",
            "/api/quota/status",
            "/api/settings",
            "/api/countries",
            "/api/businesses",
            "/api/admin/users",
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
