from redis.asyncio import Redis, from_url

from harness.config import get_settings

_client: Redis = from_url(
    get_settings().redis_url,
    decode_responses=True,
    max_connections=10,
    # Hosted Redis (Upstash) drops idle connections; without these a request on a
    # dead pooled socket hangs with no timeout instead of reconnecting.
    socket_timeout=5,
    socket_connect_timeout=5,
    socket_keepalive=True,
    health_check_interval=30,
    retry_on_timeout=True,
)


def get_redis() -> Redis:
    return _client
