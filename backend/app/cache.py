"""Redis 缓存封装：惰性连接 + 优雅降级。

Redis 不是启动的必要条件——连不上时置 available=False，后续 get/set/delete
全部安全空转（get 返回 None，调用方回退到数据库）。这样本地 dev（SQLite、无 Redis）
也能正常跑，Docker 里才真正命中缓存。
"""
import json
import logging
from typing import Any, Optional

import redis.asyncio as redis

from app.config import settings

logger = logging.getLogger(__name__)

_TTL_SECONDS = 600  # 会话历史缓存 10 分钟


class _RedisCache:
    def __init__(self) -> None:
        self._client: Optional[redis.Redis] = None
        self._available: Optional[bool] = None  # None=未探测，True/False=已探测

    async def _get_client(self) -> Optional[redis.Redis]:
        if self._available is False:
            return None
        if self._client is None:
            self._client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        if self._available is True:
            return self._client
        # 首次探测：ping 一次，决定后续是否走缓存
        try:
            await self._client.ping()
            self._available = True
            return self._client
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Redis 不可用，降级为不走缓存：{e}")
            self._available = False
            return None

    async def get_json(self, key: str) -> Optional[Any]:
        client = await self._get_client()
        if client is None:
            return None
        try:
            raw = await client.get(key)
            return json.loads(raw) if raw is not None else None
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Redis get 失败 {key}: {e}")
            return None

    async def set_json(self, key: str, value: Any, ttl: int = _TTL_SECONDS) -> None:
        client = await self._get_client()
        if client is None:
            return
        try:
            await client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Redis set 失败 {key}: {e}")

    async def delete(self, key: str) -> None:
        client = await self._get_client()
        if client is None:
            return
        try:
            await client.delete(key)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Redis delete 失败 {key}: {e}")


cache = _RedisCache()
