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

import asyncio
import logging

import redis.asyncio as redis


logger: logging.Logger = logging.getLogger(__name__)


class Redis:
    def __init__(self, *, url: str | None = None) -> None:
        url = url or "redis://localhost:6379/0"
        pool = redis.ConnectionPool.from_url(url, decode_responses=True)  # type: ignore

        self.pool: redis.Redis = redis.Redis.from_pool(pool)
        self.url = url

        self._could_connect: bool | None = None
        self._task = asyncio.create_task(self._health_task())

    @property
    def could_connect(self) -> bool | None:
        return self._could_connect

    async def ping(self) -> bool:
        try:
            async with asyncio.timeout(3.0):
                self._could_connect = bool(await self.pool.ping())  # type: ignore
        except Exception:
            if self._could_connect is not False:
                logger.warning(
                    "Unable to connect to Redis: %s. Services relying on this instance will now be in-memory.", self.url
                )

            self._could_connect = False

        return self._could_connect

    async def _health_task(self) -> None:
        while True:
            previous = self.could_connect
            await self.ping()

            if not previous and self.could_connect:
                logger.info("Redis connection has been (re)established: %s", self.url)

            await asyncio.sleep(5)
