from fastapi import HTTPException, Request, status
from typing import Optional, Any

import json
import logging

import redis
from .config import settings



logger = logging.getLogger(__name__)

# Initialize Redis client with graceful fallback
try:
    redis_client = redis.from_url(settings.redis_url, decode_responses=True)
except Exception as e:
    logger.warning(f"Could not connect to Redis: {e}")
    redis_client = None


def get_cached_json(key: str) -> Optional[Any]:
    """Retrieves and deserializes JSON from Redis cache."""
    if not redis_client:
        return None
    try:
        data = redis_client.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        logger.warning(f"Redis cache read error on '{key}': {e}")
    return None


def set_cached_json(key: str, data: Any, expire_seconds: int = 180):
    """Serializes and stores data in Redis cache with an expiration time."""
    if not redis_client:
        return
    try:
        serialized = json.dumps(data, default=str)
        redis_client.set(key, serialized, ex=expire_seconds)
    except Exception as e:
        logger.warning(f"Redis cache write error on '{key}': {e}")


def delete_cache_pattern(pattern: str):
    """
    Non-blocking cache invalidation using scan_iter.
    Safe for production on large Redis keyspaces.
    """
    if not redis_client:
        return
    try:
        keys = list(redis_client.scan_iter(match=pattern, count=100))
        if keys:
            redis_client.delete(*keys)
    except Exception as e:
        logger.warning(f"Redis cache invalidation error for '{pattern}': {e}")


class RateLimiter:
    """
    FastAPI Dependency for Rate Limiting.
    Extracts client IP securely and fails open with warnings if Redis is down.
    """

    def __init__(self, times: int, seconds: int, key_prefix: str = "rate_limit"):
        self.times = times
        self.seconds = seconds
        self.key_prefix = key_prefix

    def __call__(self, request: Request):
        if not redis_client:
            logger.warning(f"Redis offline: skipping rate limiting on {request.url.path}")
            return  # Fail-open policy if Redis is offline

        client_ip = "unknown"
        if request.client:
            client_ip = request.client.host

        # Only trust X-Forwarded-For when incoming direct peer is a trusted local proxy/container
        if client_ip in ("127.0.0.1", "::1", "localhost", "testclient"):
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                client_ip = forwarded.split(",")[0].strip()

        endpoint = request.url.path
        key = f"{self.key_prefix}:{endpoint}:{client_ip}"

        try:
            current_requests = redis_client.incr(key)
            if current_requests == 1:
                redis_client.expire(key, self.seconds)

            if current_requests > self.times:
                ttl = redis_client.ttl(key)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many requests. Limit is {self.times} per {self.seconds}s. Please retry in {ttl}s."
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Rate limiting failed open due to Redis exception on {endpoint}: {e}")
