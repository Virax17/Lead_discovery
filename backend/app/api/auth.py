from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt

from app.config.settings import settings
from app.services.users import (
    get_user_by_username,
    get_user_usage_summary,
    hash_password,
    normalize_username,
    upsert_user_account,
    touch_user_login,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=1440)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.app_secret_key, algorithm="HS256")


@router.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    username = normalize_username(form_data.username)
    user = await get_user_by_username(username)

    bootstrap_matches = {
        normalize_username(settings.bootstrap_admin_username): (
            settings.bootstrap_admin_password,
            "admin",
            settings.bootstrap_admin_credit_limit,
        ),
        normalize_username(settings.bootstrap_user_username): (
            settings.bootstrap_user_password,
            "user",
            settings.bootstrap_user_credit_limit,
        ),
    }

    if not user:
        bootstrap_match = bootstrap_matches.get(username)
        if bootstrap_match and bootstrap_match[0] and form_data.password == bootstrap_match[0]:
            await upsert_user_account(
                username,
                hash_password(form_data.password),
                role=bootstrap_match[1],
                credit_limit=bootstrap_match[2],
            )
            user = await get_user_by_username(username)

    if not user or not user.get("active", True) or not verify_password(form_data.password, user.get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    await touch_user_login(username)
    access_token = create_access_token(data={"sub": username, "role": user.get("role", "user")})
    user_summary = await get_user_usage_summary(username)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user_summary,
    }


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.app_secret_key, algorithms=["HS256"])
        username: str = normalize_username(payload.get("sub", ""))
        if not username:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = await get_user_by_username(username)
    if not user or not user.get("active", True):
        raise credentials_exception

    return username


async def get_current_user_profile(token: str = Depends(oauth2_scheme)):
    username = await get_current_user(token)
    user = await get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")
    user_summary = await get_user_usage_summary(username)
    if not user_summary:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")
    return user_summary


async def get_current_admin(current_user: dict = Depends(get_current_user_profile)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user
