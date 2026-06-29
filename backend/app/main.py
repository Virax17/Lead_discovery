from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime
from app.db.connection import get_db
from app.db.indexes import ensure_indexes

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
    yield
    # Shutdown (could close db connection here if needed)

# Initialize FastAPI app
app = FastAPI(
    title="Lead Discovery API",
    description="Backend for the Lead Discovery Automation Platform",
    version="1.0.0",
    lifespan=lifespan
)

from app.api import auth, searches, quota, settings

# Setup CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # Vite frontend
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(searches.router, prefix="/api")
app.include_router(quota.router, prefix="/api")
app.include_router(settings.router, prefix="/api")

@app.get("/")
async def root():
    return {"message": "Lead Discovery API is running"}
