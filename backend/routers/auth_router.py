"""Authentication and user management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user, require_admin
from db import get_db, hash_password, verify_password_with_migration, generate_token

router = APIRouter()


# ── Request / Response models ──────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "user"


class UpdateUserRequest(BaseModel):
    role: str


# ── Public endpoints ───────────────────────────────────────────

@router.post("/login")
async def login(req: LoginRequest):
    """Verify credentials, create session, return token + user info."""
    conn = get_db()
    try:
        # Look up user first, then verify password separately
        row = conn.execute(
            "SELECT id, username, password_hash, role, must_change_password FROM users WHERE username = ?",
            (req.username,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        if not verify_password_with_migration(req.password, row["password_hash"], row["id"]):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        token = generate_token()
        conn.execute(
            "INSERT INTO sessions (token, user_id) VALUES (?, ?)",
            (token, row["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "token": token,
        "user": {
            "id": row["id"],
            "username": row["username"],
            "role": row["role"],
            "must_change_password": bool(row["must_change_password"]),
        },
    }


# ── Authenticated endpoints ───────────────────────────────────

@router.post("/logout")
async def logout(user: dict = Depends(get_current_user)):
    """Delete the current session."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok"}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    """Return current user info (used to validate stored token on page refresh)."""
    return user


@router.post("/change-password")
async def change_password(req: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    """Change password, clear must_change_password flag."""
    conn = get_db()
    try:
        # Verify old password
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE id = ?",
            (user["id"],),
        ).fetchone()
        if not row or not verify_password_with_migration(req.old_password, row["password_hash"], row["id"]):
            raise HTTPException(status_code=400, detail="原密码错误")
        if len(req.new_password) < 6:
            raise HTTPException(status_code=400, detail="新密码长度至少6位")
        conn.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
            (hash_password(req.new_password), user["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok"}


# ── Admin-only endpoints ──────────────────────────────────────

@router.get("/users")
async def list_users(admin: dict = Depends(require_admin)):
    """List all users."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, username, role, must_change_password, created_at FROM users ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return {
        "users": [
            {
                "id": r["id"],
                "username": r["username"],
                "role": r["role"],
                "must_change_password": bool(r["must_change_password"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    }


@router.post("/users")
async def create_user(req: CreateUserRequest, admin: dict = Depends(require_admin)):
    """Create a new user."""
    if req.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="角色必须为 admin 或 user")
    if len(req.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少6位")
    conn = get_db()
    try:
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (req.username,)).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="用户名已存在")
        conn.execute(
            "INSERT INTO users (username, password_hash, role, must_change_password) VALUES (?, ?, ?, ?)",
            (req.username, hash_password(req.password), req.role, 1),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok"}


@router.put("/users/{user_id}")
async def update_user(user_id: int, req: UpdateUserRequest, admin: dict = Depends(require_admin)):
    """Update a user's role."""
    if req.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="角色必须为 admin 或 user")
    conn = get_db()
    try:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (req.role, user_id))
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok"}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, admin: dict = Depends(require_admin)):
    """Delete a user and their sessions."""
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="不能删除自己")
    conn = get_db()
    try:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok"}


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: int, admin: dict = Depends(require_admin)):
    """Reset user password to 123456, set must_change_password, clear sessions."""
    conn = get_db()
    try:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="用户不存在")
        conn.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?",
            (hash_password("123456"), user_id),
        )
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()
    return {"status": "ok"}
