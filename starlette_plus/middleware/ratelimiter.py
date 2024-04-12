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

import logging
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from ..limiter import RateLimit, Store
from ..redis import Redis


if TYPE_CHECKING:
    from starlette.routing import Route
    from starlette.types import ASGIApp, Receive, Scope, Send

    from ..redis import Redis
    from ..types_.limiter import BucketType, ExemptCallable, RateLimitData, ResponseCallback


logger: logging.Logger = logging.getLogger(__name__)


class RatelimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        ignore_localhost: bool = True,
        global_limits: list[RateLimitData] = [],
        response_callback: ResponseCallback | None = None,
        redis: Redis | None = None,
    ) -> None:
        self.app: ASGIApp = app

        self._ignore_local: bool = ignore_localhost
        self._global_limits: list[RateLimitData] = global_limits

        self._store: Store = Store(redis=redis)
        self._response_callback: ResponseCallback = response_callback or self.default_response

    async def default_response(self, request: Request, retry: float) -> Response:
        return JSONResponse(
            {"error": "You are requesting too fast."},
            status_code=429,
            headers={"Retry-After": str(retry)},
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        request: Request = Request(scope)
        forwarded: str | None = request.headers.get("X-Forwarded-For", None)

        routes: list[Route] = scope["app"].routes
        route: Route | None = None

        for r in routes:
            if r.path == request.url.path:
                route = r
                break

        route_limits: list[RateLimitData] = sorted(getattr(route, "limits", []), key=lambda x: x["priority"])

        for limit in self._global_limits + route_limits:
            is_exempt: bool = False
            exempt: ExemptCallable | None = limit["exempt"]

            if exempt is not None:
                is_exempt: bool = await exempt(request)

            if is_exempt:
                continue

            bucket: BucketType = limit["bucket"]
            if bucket == "ip":
                if not request.client and not forwarded:
                    logger.warning("Could not determine the IP address while ratelimiting! Ignoring...")
                    return await self.app(scope, receive, send)

                # forwarded or client.host will exist at this point...
                key: str = forwarded.split(",")[0] if forwarded else request.client.host  # type: ignore

                if self._ignore_local and key not in ("127.0.0.1", "::1", "localhost", "0.0.0.0"):
                    return await self.app(scope, receive, send)
            else:
                key: str | None = await bucket(request)
                if not key:
                    # Request is assumed exempt from ratelimiting...
                    return await self.app(scope, receive, send)

            encapsulated: RateLimit = RateLimit(limit["rate"], limit["per"])
            if retry := await self._store.update(key, encapsulated):
                response: Response = await self._response_callback(request, retry)
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)
