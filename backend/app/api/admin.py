from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import get_current_admin
from app.db.connection import get_db
from app.models.schemas import UserCreate, UserActiveUpdate, UserPasswordUpdate
from app.services.country_maintenance import normalize_all_countries
from app.services.users import (
    create_user,
    get_user_by_username,
    list_users_with_usage,
    get_user_usage_summary,
    normalize_username,
    set_user_active,
    set_user_password,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/normalize-countries")
async def normalize_countries(current_user: dict = Depends(get_current_admin)):
    db = get_db()
    merges = await normalize_all_countries(db)
    return {"merges": merges}


@router.get("/users")
async def list_admin_users(current_user: dict = Depends(get_current_admin)):
    return await list_users_with_usage()


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_admin_user(user_in: UserCreate, current_user: dict = Depends(get_current_admin)):
    username = normalize_username(user_in.username)
    existing = await get_user_by_username(username)
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists")

    await create_user(username, user_in.password, role=user_in.role, credit_limit=user_in.credit_limit)
    summary = await get_user_usage_summary(username)
    return summary


@router.put("/users/{username}/password")
async def update_admin_user_password(
    username: str,
    payload: UserPasswordUpdate,
    current_user: dict = Depends(get_current_admin),
):
    normalized = normalize_username(username)
    existing = await get_user_by_username(normalized)
    if not existing:
        raise HTTPException(status_code=404, detail="User not found")

    await set_user_password(normalized, payload.password)
    summary = await get_user_usage_summary(normalized)
    return summary


@router.put("/users/{username}/active")
async def update_admin_user_active(
    username: str,
    payload: UserActiveUpdate,
    current_user: dict = Depends(get_current_admin),
):
    normalized = normalize_username(username)
    existing = await get_user_by_username(normalized)
    if not existing:
        raise HTTPException(status_code=404, detail="User not found")

    if normalized == normalize_username(current_user["username"]) and not payload.active:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")

    await set_user_active(normalized, payload.active)
    summary = await get_user_usage_summary(normalized)
    return summary
