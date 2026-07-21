from __future__ import annotations

from datetime import datetime
from typing import Any

import bcrypt

from app.config.settings import settings
from app.db.connection import get_db


def normalize_username(username: str) -> str:
    return username.strip().lower()


def current_month_str() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False


def _public_user_doc(user_doc: dict[str, Any], usage_doc: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "_id": user_doc.get("username"),
        "username": user_doc.get("username"),
        "role": user_doc.get("role", "user"),
        "active": user_doc.get("active", True),
        "credit_limit": user_doc.get("credit_limit", 0),
        "created_at": user_doc.get("created_at"),
        "updated_at": user_doc.get("updated_at"),
        "last_login_at": user_doc.get("last_login_at"),
    }

    if usage_doc is not None:
        used = usage_doc.get("credits_used", 0)
        limit = payload["credit_limit"]
        payload["year_month"] = usage_doc.get("year_month", current_month_str())
        payload["credits_used"] = used
        payload["credits_remaining"] = max(0, limit - used) if limit else None

    return payload


async def get_user_by_username(username: str) -> dict[str, Any] | None:
    db = get_db()
    return await db.users.find_one({"username": normalize_username(username)})


async def get_current_month_usage(username: str) -> dict[str, Any]:
    db = get_db()
    normalized = normalize_username(username)
    month_key = f"{current_month_str()}:{normalized}"
    usage = await db.user_credits_monthly.find_one({"_id": month_key})
    return usage or {
        "_id": month_key,
        "username": normalized,
        "year_month": current_month_str(),
        "credits_used": 0,
        "updated_at": datetime.utcnow(),
    }


async def increment_user_usage(username: str, amount: int = 1) -> None:
    db = get_db()
    normalized = normalize_username(username)
    month_key = f"{current_month_str()}:{normalized}"
    await db.user_credits_monthly.update_one(
        {"_id": month_key},
        {
            "$inc": {"credits_used": amount},
            "$set": {
                "username": normalized,
                "year_month": current_month_str(),
                "updated_at": datetime.utcnow(),
            },
        },
        upsert=True,
    )


async def touch_user_login(username: str) -> None:
    db = get_db()
    normalized = normalize_username(username)
    await db.users.update_one(
        {"username": normalized},
        {"$set": {"last_login_at": datetime.utcnow(), "updated_at": datetime.utcnow()}},
    )


async def seed_bootstrap_users() -> None:
    seeds: list[dict[str, Any]] = []

    if settings.bootstrap_admin_username and settings.bootstrap_admin_password:
        seeds.append({
            "username": normalize_username(settings.bootstrap_admin_username),
            "password_hash": hash_password(settings.bootstrap_admin_password),
            "role": "admin",
            "credit_limit": settings.bootstrap_admin_credit_limit,
        })

    if settings.bootstrap_user_username and settings.bootstrap_user_password:
        seeds.append({
            "username": normalize_username(settings.bootstrap_user_username),
            "password_hash": hash_password(settings.bootstrap_user_password),
            "role": "user",
            "credit_limit": settings.bootstrap_user_credit_limit,
        })

    for seed in seeds:
        await upsert_user_account(
            seed["username"],
            seed["password_hash"],
            role=seed["role"],
            credit_limit=seed["credit_limit"],
        )


async def upsert_user_account(username: str, password_hash: str, role: str = "user", credit_limit: int = 1000) -> dict[str, Any]:
    db = get_db()
    normalized = normalize_username(username)
    now = datetime.utcnow()
    payload = {
        "username": normalized,
        "password_hash": password_hash,
        "role": role,
        "active": True,
        "credit_limit": credit_limit,
        "updated_at": now,
    }
    existing = await db.users.find_one({"username": normalized})
    if existing:
        await db.users.update_one(
            {"username": normalized},
            {"$set": payload},
        )
        payload["created_at"] = existing.get("created_at", now)
        payload["last_login_at"] = existing.get("last_login_at")
    else:
        payload["created_at"] = now
        payload["last_login_at"] = None
        await db.users.insert_one(payload)
    return payload


async def create_user(username: str, password: str, role: str = "user", credit_limit: int = 1000) -> dict[str, Any]:
    db = get_db()
    normalized = normalize_username(username)
    now = datetime.utcnow()
    payload = {
        "username": normalized,
        "password_hash": hash_password(password),
        "role": role,
        "active": True,
        "credit_limit": credit_limit,
        "created_at": now,
        "updated_at": now,
        "last_login_at": None,
    }
    await db.users.insert_one(payload)
    return payload


async def set_user_password(username: str, new_password: str) -> bool:
    db = get_db()
    normalized = normalize_username(username)
    result = await db.users.update_one(
        {"username": normalized},
        {"$set": {"password_hash": hash_password(new_password), "updated_at": datetime.utcnow()}},
    )
    return result.matched_count > 0


async def set_user_active(username: str, active: bool) -> bool:
    db = get_db()
    normalized = normalize_username(username)
    result = await db.users.update_one(
        {"username": normalized},
        {"$set": {"active": active, "updated_at": datetime.utcnow()}},
    )
    return result.matched_count > 0


async def list_users_with_usage() -> list[dict[str, Any]]:
    db = get_db()
    users = await db.users.find().sort("created_at", -1).to_list(length=None)
    month = current_month_str()
    results: list[dict[str, Any]] = []
    for user in users:
        usage = await db.user_credits_monthly.find_one({"_id": f"{month}:{user['username']}"})
        results.append(_public_user_doc(user, usage))
    return results


async def get_user_usage_summary(username: str) -> dict[str, Any] | None:
    user = await get_user_by_username(username)
    if not user:
        return None
    usage = await get_current_month_usage(username)
    return _public_user_doc(user, usage)
