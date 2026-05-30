import redis.asyncio as aioredis
import hashlib
import os
from typing import Optional
from schemas import ResumeSchema, InterviewSessionState

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
SESSION_TTL = 60 * 60 * 4   # 4 hours
RESUME_CACHE_TTL = 60 * 60  # 1 hour

_client: Optional[aioredis.Redis] = None


async def get_client() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = await aioredis.from_url(REDIS_URL, decode_responses=True)
    return _client


# ── Resume schema caching ─────────────────────────────────────────────────────

def _resume_key(resume_text: str) -> str:
    digest = hashlib.sha256(resume_text.encode()).hexdigest()
    return f"cache:resume:{digest}"


async def get_cached_resume_schema(resume_text: str) -> Optional[ResumeSchema]:
    try:
        client = await get_client()
        cached = await client.get(_resume_key(resume_text))
        if cached:
            return ResumeSchema.model_validate_json(cached)
    except Exception:
        pass
    return None


async def set_cached_resume_schema(resume_text: str, schema: ResumeSchema) -> None:
    try:
        client = await get_client()
        await client.setex(_resume_key(resume_text), RESUME_CACHE_TTL, schema.model_dump_json())
    except Exception:
        pass


# ── Session persistence ───────────────────────────────────────────────────────

def _session_key(session_id: str) -> str:
    return f"session:{session_id}"


async def save_session(state: InterviewSessionState) -> None:
    try:
        client = await get_client()
        await client.setex(_session_key(state.session_id), SESSION_TTL, state.model_dump_json())
    except Exception:
        pass


async def load_session(session_id: str) -> Optional[InterviewSessionState]:
    try:
        client = await get_client()
        data = await client.get(_session_key(session_id))
        if data:
            return InterviewSessionState.model_validate_json(data)
    except Exception:
        pass
    return None


async def delete_session(session_id: str) -> None:
    try:
        client = await get_client()
        await client.delete(_session_key(session_id))
    except Exception:
        pass
