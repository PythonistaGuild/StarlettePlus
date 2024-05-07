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

import redis.asyncio as redis


class Redis:
    def __init__(self, *, url: str | None = None) -> None:
        url = url or "redis://localhost:6379/0"
        pool = redis.ConnectionPool.from_url(url, decode_responses=True)  # type: ignore

        self.pool: redis.Redis = redis.Redis.from_pool(pool)

    async def ping(self) -> bool:
        return bool(await self.pool.ping())  # type: ignore
