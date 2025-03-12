import json
import httpx
import time
from typing import Any, Optional, Dict
from ..config import REDIS_URL, REDIS_TOKEN

# Headers for Redis REST API
HEADERS = {"Authorization": f"Bearer {REDIS_TOKEN}"} if REDIS_TOKEN else {}

# Cache TTLs (in seconds)
ALBUM_TTL = 604800     # 1 week
SIMILAR_TTL = 86400    # 1 day
USER_TTL = 3600        # 1 hour
SEARCH_TTL = 43200     # 12 hours

# In-memory cache fallback
memory_cache: Dict[str, Dict[str, Any]] = {}


async def set_cache(key: str, value: Any, expire_seconds: int = 3600) -> None:
    """
    Set a value in Redis cache with expiration.
    Falls back to in-memory cache if Redis is not available.
    """
    # First, try to use Redis REST API
    if REDIS_URL and REDIS_TOKEN:
        try:
            value_str = json.dumps(value)
            pipeline_data = [["SET", key, value_str], ["EXPIRE", key, str(expire_seconds)]]

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{REDIS_URL}/pipeline", headers=HEADERS, json=pipeline_data, timeout=5.0
                )
                response.raise_for_status()
                return

        except Exception as e:
            print(f"Error setting Redis cache: {str(e)}")
            # Fall through to memory cache

    # Use in-memory cache as fallback
    memory_cache[key] = {
        "value": value,
        "expires_at": time.time() + expire_seconds
    }


async def get_cache(key: str) -> Optional[Any]:
    """
    Get a value from Redis cache.
    Falls back to in-memory cache if Redis is not available.
    """
    # First, try to use Redis REST API
    if REDIS_URL and REDIS_TOKEN:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{REDIS_URL}/get/{key}", headers=HEADERS, timeout=5.0
                )
                response.raise_for_status()

                data = response.json()
                if data.get("result"):
                    return json.loads(data["result"])

        except Exception as e:
            print(f"Error getting Redis cache: {str(e)}")
            # Fall through to memory cache

    # Check in-memory cache as fallback
    if key in memory_cache:
        cache_item = memory_cache[key]
        if cache_item["expires_at"] > time.time():
            return cache_item["value"]
        else:
            # Remove expired item
            del memory_cache[key]

    return None


async def delete_cache(key: str) -> None:
    """
    Delete a value from Redis cache and in-memory cache.
    """
    # Try to delete from Redis
    if REDIS_URL and REDIS_TOKEN:
        try:
            async with httpx.AsyncClient() as client:
                await client.get(f"{REDIS_URL}/del/{key}", headers=HEADERS, timeout=5.0)
        except Exception as e:
            print(f"Error deleting Redis cache: {str(e)}")

    # Also remove from memory cache if present
    if key in memory_cache:
        del memory_cache[key]


async def clear_cache_pattern(pattern: str) -> None:
    """
    Clear all cache keys matching a pattern.
    Example: clear_cache_pattern("album:*") clears all album caches
    """
    if REDIS_URL and REDIS_TOKEN:
        try:
            async with httpx.AsyncClient() as client:
                # Get keys matching pattern
                response = await client.get(
                    f"{REDIS_URL}/keys/{pattern}", headers=HEADERS, timeout=5.0
                )
                response.raise_for_status()
                data = response.json()
                
                if data.get("result") and isinstance(data["result"], list):
                    # Delete each key
                    for key in data["result"]:
                        await delete_cache(key)
                        
        except Exception as e:
            print(f"Error clearing cache pattern: {str(e)}")
    
    # Clear matching keys from memory cache
    if "*" in pattern:
        prefix = pattern.split("*")[0]
        keys_to_delete = [k for k in memory_cache.keys() if k.startswith(prefix)]
        for key in keys_to_delete:
            del memory_cache[key]
    else:
        # Exact match
        if pattern in memory_cache:
            del memory_cache[pattern]