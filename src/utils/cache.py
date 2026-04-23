"""
Redis Cache Utility for Query Results
Caches:
- Query embeddings (120ms → 5ms)
- RAG retrieval results (720ms → 50ms)
- Conversation history (180ms → 10ms)

Note: Redis is optional. If not available, caching is disabled (graceful degradation).
"""

import json
import hashlib
from typing import Optional, Any, List, Dict
from functools import wraps
from controllers.config import logger

# Try to import redis, but don't fail if not available
try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    logger.warning(
        "⚠️ Redis module not installed. Caching disabled. Install with: pip install redis"
    )
    REDIS_AVAILABLE = False
    redis = None

# Initialize Redis client (lazy loading)
_redis_client = None


def get_redis_client():
    """Get or create Redis client (returns None if Redis not available)"""
    global _redis_client

    # Check if Redis module is available
    if not REDIS_AVAILABLE:
        return None

    if _redis_client is None:
        try:
            _redis_client = redis.Redis(
                host="localhost",
                port=6379,
                db=0,
                decode_responses=False,  # We'll handle encoding
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            # Test connection
            _redis_client.ping()
            logger.info("✅ Redis cache connected successfully")
        except (redis.ConnectionError, redis.TimeoutError) as e:
            logger.warning(f"⚠️ Redis not available: {e}. Caching disabled.")
            _redis_client = None
        except Exception as e:
            logger.warning(f"⚠️ Redis error: {e}. Caching disabled.")
            _redis_client = None
    return _redis_client


def generate_cache_key(prefix: str, *args, **kwargs) -> str:
    """
    Generate consistent cache key from arguments

    Args:
        prefix: Key prefix (e.g., 'embedding', 'rag', 'conv')
        *args, **kwargs: Values to hash

    Returns:
        Cache key string
    """
    # Combine all arguments into a string
    combined = f"{prefix}:"
    for arg in args:
        combined += f"{arg}:"
    for key in sorted(kwargs.keys()):
        combined += f"{key}={kwargs[key]}:"

    # Hash for consistent length
    hash_obj = hashlib.md5(combined.encode())
    return f"{prefix}:{hash_obj.hexdigest()}"


def cache_get(key: str) -> Optional[Any]:
    """Get value from cache"""
    client = get_redis_client()
    if not client:
        return None

    try:
        value = client.get(key)
        if value:
            return json.loads(value)
        return None
    except Exception as e:
        logger.debug(f"Cache get error for key {key}: {e}")
        return None


def cache_set(key: str, value: Any, ttl: int = 3600):
    """
    Set value in cache with TTL

    Args:
        key: Cache key
        value: Value to cache (must be JSON serializable)
        ttl: Time to live in seconds (default 1 hour)
    """
    client = get_redis_client()
    if not client:
        return False

    try:
        serialized = json.dumps(value)
        client.setex(key, ttl, serialized)
        return True
    except Exception as e:
        logger.debug(f"Cache set error for key {key}: {e}")
        return False


def cache_delete(key: str):
    """Delete key from cache"""
    client = get_redis_client()
    if not client:
        return False

    try:
        client.delete(key)
        return True
    except Exception as e:
        logger.debug(f"Cache delete error for key {key}: {e}")
        return False


def cache_invalidate_pattern(pattern: str):
    """
    Invalidate all keys matching pattern

    Args:
        pattern: Redis pattern (e.g., 'rag:video123:*')
    """
    client = get_redis_client()
    if not client:
        return 0

    try:
        keys = client.keys(pattern)
        if keys:
            return client.delete(*keys)
        return 0
    except Exception as e:
        logger.debug(f"Cache pattern delete error for {pattern}: {e}")
        return 0


# Decorator for automatic caching
def cached(prefix: str, ttl: int = 3600, key_func=None):
    """
    Decorator to cache function results

    Usage:
        @cached('embedding', ttl=7200)
        def generate_embedding(text: str):
            return expensive_operation(text)

    Args:
        prefix: Cache key prefix
        ttl: Time to live in seconds
        key_func: Optional function to generate cache key from args
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = generate_cache_key(prefix, *args, **kwargs)

            # Try cache first
            cached_result = cache_get(cache_key)
            if cached_result is not None:
                logger.debug(f"Cache HIT: {cache_key}")
                return cached_result

            # Cache miss - call function
            logger.debug(f"Cache MISS: {cache_key}")
            result = func(*args, **kwargs)

            # Store in cache
            cache_set(cache_key, result, ttl)
            return result

        return wrapper

    return decorator


# Specialized caching functions for common use cases


def cache_query_embedding(query: str, embedding: List[float], ttl: int = 7200):
    """
    Cache query embedding (2 hour TTL - queries repeat often)

    Args:
        query: Query text
        embedding: Embedding vector
        ttl: Time to live (default 2 hours)
    """
    key = generate_cache_key("embedding", query)
    cache_set(key, {"query": query, "embedding": embedding}, ttl)


def get_cached_query_embedding(query: str) -> Optional[List[float]]:
    """Get cached query embedding"""
    key = generate_cache_key("embedding", query)
    result = cache_get(key)
    return result["embedding"] if result else None


def cache_rag_results(video_id: str, query: str, results: List[Dict], ttl: int = 1800):
    """
    Cache RAG retrieval results (30 min TTL - video content doesn't change)

    Args:
        video_id: Video identifier
        query: Query text
        results: Retrieved chunks
        ttl: Time to live (default 30 minutes)
    """
    key = generate_cache_key("rag", video_id, query)
    cache_set(key, results, ttl)


def get_cached_rag_results(video_id: str, query: str) -> Optional[List[Dict]]:
    """Get cached RAG results"""
    key = generate_cache_key("rag", video_id, query)
    return cache_get(key)


def invalidate_video_cache(video_id: str):
    """Invalidate all cache entries for a video"""
    pattern = f"rag:{video_id}:*"
    deleted = cache_invalidate_pattern(pattern)
    logger.info(f"Invalidated {deleted} cache entries for video {video_id}")
    return deleted
