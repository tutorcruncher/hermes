import redis.asyncio as redis

from app.core.config import settings

redis_client = redis.from_url(settings.redis_url or 'redis://localhost:6379')
