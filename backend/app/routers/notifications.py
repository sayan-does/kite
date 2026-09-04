from fastapi import APIRouter
from fastapi import Depends as depends
from fastapi import HTTPException
from pydantic import BaseModel

from app.auth import get_current_user_id
from app.db import supabase

router = APIRouter()

CATEGORIES = ["discovery", "dependency"]
CHANNELS = ["in_app", "email"]


def _ensure_notification_settings(user_id: str):
    supabase.table("profiles").upsert({"id": user_id}, on_conflict="id").execute()
    existing = supabase.table("notification_settings").select("category, channel").eq("user_id", user_id).execute()
    existing_set = {(row["category"], row["channel"]) for row in (existing.data or [])}
    missing = []
    for cat in CATEGORIES:
        for ch in CHANNELS:
            if (cat, ch) not in existing_set:
                missing.append({"user_id": user_id, "category": cat, "channel": ch, "enabled": True})
    if missing:
        supabase.table("notification_settings").insert(missing).execute()


@router.get("/me/notification-settings")
async def get_notification_settings(user_id: str = depends(get_current_user_id)):
    _ensure_notification_settings(user_id)
    result = supabase.table("notification_settings").select("category, channel, enabled").eq("user_id", user_id).execute()
    settings: dict[str, dict[str, bool]] = {}
    for row in (result.data or []):
        cat = row["category"]
        if cat not in settings:
            settings[cat] = {}
        settings[cat][row["channel"]] = row["enabled"]
    return {"settings": settings}


class ChannelSettings(BaseModel):
    in_app: bool = True
    email: bool = True


class PutNotificationSettingsBody(BaseModel):
    discovery: ChannelSettings = ChannelSettings()
    dependency: ChannelSettings = ChannelSettings()


@router.put("/me/notification-settings")
async def put_notification_settings(
    body: PutNotificationSettingsBody,
    user_id: str = depends(get_current_user_id),
):
    _ensure_notification_settings(user_id)
    for cat in CATEGORIES:
        channels = getattr(body, cat)
        for ch in CHANNELS:
            enabled = getattr(channels, ch)
            supabase.table("notification_settings").update({"enabled": enabled}).eq(
                "user_id", user_id
            ).eq("category", cat).eq("channel", ch).execute()
    result = supabase.table("notification_settings").select("category, channel, enabled").eq("user_id", user_id).execute()
    settings: dict[str, dict[str, bool]] = {}
    for row in (result.data or []):
        cat = row["category"]
        if cat not in settings:
            settings[cat] = {}
        settings[cat][row["channel"]] = row["enabled"]
    return {"settings": settings}
