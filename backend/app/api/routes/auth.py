"""
Auth routes — signup, login, me (GET + PATCH).

All route functions are plain `def` (not async) so FastAPI runs them in a
thread pool, keeping synchronous sqlite3 calls off the event loop.
"""

import json
import uuid
from datetime import datetime, timedelta

import bcrypt
from fastapi import APIRouter, Header, HTTPException, status
from jose import JWTError, jwt

from ...core.config import settings
from ...core.database import (
    db_create_user,
    db_get_user_by_email,
    db_get_user_by_id,
    db_update_user,
)
from ...models.schemas import (
    AuthResponse,
    AuthUser,
    InterestCategory,
    UserCreate,
    UserLogin,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=10)).decode()


def _verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _create_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _decode_token(token: str) -> str:
    """Return user_id from token, raise 401 if invalid/expired."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        return user_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def get_current_user_id(authorization: str = Header()) -> str:
    """Extract and validate Bearer token from the Authorization header."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header must be 'Bearer <token>'")
    token = authorization[len("Bearer "):]
    return _decode_token(token)


def _row_to_auth_user(row) -> AuthUser:
    """Convert a sqlite3.Row into an AuthUser schema instance."""
    raw_interests = row["interests"] or "[]"
    try:
        interests_list = json.loads(raw_interests)
    except (json.JSONDecodeError, TypeError):
        interests_list = []

    interests = [InterestCategory(i) for i in interests_list if i in InterestCategory._value2member_map_]

    return AuthUser(
        user_id=row["user_id"],
        username=row["username"],
        email=row["email"],
        target_language=row["target_language"],
        proficiency_level=row["proficiency_level"],
        interests=interests,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(body: UserCreate) -> AuthResponse:
    user_id = str(uuid.uuid4())
    hashed = _hash_password(body.password)

    row = db_create_user(
        user_id=user_id,
        username=body.username,
        email=body.email,
        hashed_password=hashed,
        target_language=body.target_language.value,
    )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email or username already registered",
        )

    token = _create_token(user_id)
    return AuthResponse(access_token=token, user=_row_to_auth_user(row))


@router.post("/login", response_model=AuthResponse)
def login(body: UserLogin) -> AuthResponse:
    row = db_get_user_by_email(body.email)
    if row is None or not _verify_password(body.password, row["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = _create_token(row["user_id"])
    return AuthResponse(access_token=token, user=_row_to_auth_user(row))


@router.get("/me", response_model=AuthUser)
def get_me(authorization: str = Header()) -> AuthUser:
    user_id = get_current_user_id(authorization)
    row = db_get_user_by_id(user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return _row_to_auth_user(row)


@router.patch("/me", response_model=AuthUser)
def patch_me(
    body: dict,
    authorization: str = Header(),
) -> AuthUser:
    user_id = get_current_user_id(authorization)

    allowed_fields = {"proficiency_level", "target_language", "interests"}
    update_kwargs: dict = {}

    for key in allowed_fields:
        if key in body:
            value = body[key]
            if key == "interests" and isinstance(value, list):
                # Normalize enum values to strings for storage
                update_kwargs[key] = [
                    v.value if hasattr(v, "value") else str(v) for v in value
                ]
            else:
                update_kwargs[key] = value.value if hasattr(value, "value") else value

    row = db_update_user(user_id, **update_kwargs)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return _row_to_auth_user(row)
