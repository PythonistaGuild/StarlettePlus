"""Copyright 2024 PythonistaGuild

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING, TypedDict


if TYPE_CHECKING:
    from .redis import Redis


logger: logging.Logger = logging.getLogger(__name__)


class TatStore(TypedDict):
    tat: datetime.datetime
    limit: RateLimit


class RateLimit:
    def __init__(self, rate: int, per: float) -> None:
        self.rate: int = rate
        self.period: datetime.timedelta = datetime.timedelta(seconds=per)

    @property
    def inverse(self) -> float:
        return self.period.total_seconds() / self.rate


class Store:
    def __init__(self, redis: Redis | None = None) -> None:
        self.redis: Redis | None = redis
        self._keys: dict[str, TatStore] = {}

    async def get_tat(self, key: str, /) -> datetime.datetime:
        now: datetime.datetime = datetime.datetime.now(tz=datetime.UTC)

        if self.redis:
            value: str | None = await self.redis.pool.get(key)  # type: ignore
            return datetime.datetime.fromisoformat(value) if value else now  # type: ignore

        return self._keys.get(key, {"tat": now}).get("tat", now)

    async def set_tat(self, key: str, /, *, tat: datetime.datetime, limit: RateLimit) -> None:
        if self.redis:
            await self.redis.pool.set(key, tat.isoformat(), ex=int(limit.period.total_seconds() + 60))  # type: ignore
        else:
            self._keys[key] = {"tat": tat, "limit": limit}

    async def update(self, key: str, limit: RateLimit) -> bool | float:
        now: datetime.datetime = datetime.datetime.now(tz=datetime.UTC)
        tat: datetime.datetime = max(await self.get_tat(key), now)

        # Clear stale keys...
        for ek, ev in self._keys.copy().items():
            if (now - ev["tat"]).total_seconds() > ev["limit"].period.total_seconds() + 60:
                del self._keys[ek]

        separation: float = (tat - now).total_seconds()
        max_interval: float = limit.period.total_seconds() - limit.inverse

        if separation > max_interval:
            return separation - max_interval

        new_tat: datetime.datetime = max(tat, now) + datetime.timedelta(seconds=limit.inverse)
        await self.set_tat(key, tat=new_tat, limit=limit)

        return False
