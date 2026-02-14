"""FastAPI dependency functions for authentication."""

from fastapi import Depends, HTTPException, Request

from db import get_db


async def get_current_user(request: Request) -> dict:
    """Extract and validate Bearer token, return user dict."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = auth[7:]
    conn = get_db()
    try:
        row = conn.execute(
            """SELECT u.id, u.username, u.role, u.must_change_password
               FROM sessions s JOIN users u ON s.user_id = u.id
               WHERE s.token = ?""",
            (token,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="登录已过期")
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "must_change_password": bool(row["must_change_password"]),
    }


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Require the current user to be an admin."""
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
