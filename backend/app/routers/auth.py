from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import supabase

router = APIRouter()


class AuthCallbackBody(BaseModel):
    access_token: str


@router.post("/auth/callback")
async def auth_callback(body: AuthCallbackBody):
    try:
        user = supabase.auth.get_user(body.access_token)
        if user is None or user.user is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        user_id = str(user.user.id)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    supabase.table("profiles").upsert({"id": user_id}, on_conflict="id").execute()
    return {"id": user_id}
