"""Serves the generated app with hand-written routes mounted next to it."""

from fastapi import APIRouter

from app import app

router = APIRouter(prefix="/api/v1/extensions")


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(router)
