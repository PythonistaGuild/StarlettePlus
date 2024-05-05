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

import asyncio
import inspect
import logging
from collections.abc import Callable, Coroutine, Iterator, Sequence
from typing import TYPE_CHECKING, Any, ClassVar, Self, TypeAlias, TypedDict, Unpack

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.types import Receive, Scope, Send

from .types_.core import RouteCoro


if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

    from .types_.core import Methods, RouteOptions
    from .types_.limiter import BucketType, ExemptCallable, RateLimitData


access_logger: logging.Logger = logging.getLogger("Route")


class ApplicationOptions(TypedDict, total=False):
    prefix: str
    views: list[View]
    access_log: bool
    middleware: list[Middleware]
    on_startup: list[Callable[[], Coroutine[Any, Any, None]]]
    on_shutdown: list[Callable[[], Coroutine[Any, Any, None]]]
    routes: Sequence[Route | WebSocketRoute | Mount]


__all__ = ("Application", "View", "route", "limit")


class LoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method: str = scope["method"]
        path: str = scope["path"]
        client: str = f"{scope['client'][0]}:{scope['client'][1]}"
        version: str = scope["http_version"]

        async def inspect_response(message: Message) -> None:
            nonlocal method, path, client, version

            if message["type"] == "http.response.start":
                status_code: int = message.get("status", 200)
                msg: str = f'{client} - "{method} {path} HTTP/{version}" '

                access_logger.info(msg, extra={"status": status_code})

            await send(message)

        await self.app(scope, receive, inspect_response)


class _Route:
    def __init__(self, **kwargs: Unpack[RouteOptions]) -> None:
        self._path: str = kwargs["path"]
        self._coro: Callable[..., RouteCoro] = kwargs["coro"]
        self._methods: Methods = kwargs["methods"]
        self._prefix: bool = kwargs["prefix"]
        self._limits: list[RateLimitData] = kwargs.get("limits", [])
        self._is_websocket: bool = kwargs.get("websocket", False)
        self._view: View | None = None
        self._include_in_schema: bool = kwargs["include_in_schema"]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> Any:
        request: Request = Request(scope, receive, send)
        response: Response | None = await self._coro(self._view, request)

        if not response:
            return Response(status_code=204)

        await response(scope, receive, send)


LimitDecorator: TypeAlias = Callable[..., RouteCoro] | _Route
T_LimitDecorator: TypeAlias = Callable[..., LimitDecorator]


def route(
    path: str,
    /,
    *,
    methods: Methods = ["GET"],
    prefix: bool = True,
    websocket: bool = False,
    include_in_schema: bool = True,
) -> Callable[..., _Route]:
    def decorator(coro: Callable[..., RouteCoro]) -> _Route:
        if not asyncio.iscoroutinefunction(coro):
            raise RuntimeError("Route callback must be a coroutine function.")

        disallowed: list[str] = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
        if coro.__name__.upper() in disallowed:
            raise ValueError(f"Route callback function must not be named any: {', '.join(disallowed)}")

        limits: list[RateLimitData] = getattr(coro, "__limits__", [])
        return _Route(
            path=path,
            coro=coro,
            methods=methods,
            prefix=prefix,
            limits=limits,
            websocket=websocket,
            include_in_schema=include_in_schema,
        )

    return decorator


def limit(
    rate: int,
    per: float,
    *,
    bucket: BucketType = "ip",
    priority: int = 0,
    exempt: ExemptCallable | None = None,
    is_global: bool = False,
) -> T_LimitDecorator:
    def decorator(coro: Callable[..., RouteCoro] | _Route) -> LimitDecorator:
        limits: RateLimitData = {
            "rate": rate,
            "per": per,
            "bucket": bucket,
            "priority": priority,
            "exempt": exempt,
            "is_global": False,
        }

        if isinstance(coro, _Route):
            coro._limits.append(limits)
        else:
            try:
                coro.__limits__.append(limits)  # type: ignore
            except AttributeError:
                setattr(coro, "__limits__", [limits])

        return coro

    return decorator


class Application(Starlette):
    __routes__: list[Route | WebSocketRoute]

    def __init__(self, *args: Any, **kwargs: Unpack[ApplicationOptions]) -> None:
        self._views: list[View] = []

        self._prefix: str = kwargs.pop("prefix", "")
        self._access_log: bool = kwargs.pop("access_log", True)
        views: list[View] = kwargs.pop("views", [])

        middleware_: list[Middleware] = kwargs.pop("middleware", [])
        middleware_.insert(0, Middleware(LoggingMiddleware)) if self._access_log else None

        super().__init__(*args, **kwargs, middleware=middleware_)  # type: ignore

        self.add_view(self)
        for view in views:
            self.add_view(view)

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        self: Self = super().__new__(cls)
        self.__routes__ = []

        name: str = cls.__name__

        for _, member in inspect.getmembers(self, predicate=lambda m: isinstance(m, _Route)):
            member._view = self
            path: str = member._path

            for method in member._methods:
                method = method.lower()

                # Due to the way Starlette works, this allows us to have schema documentation...
                setattr(member, method, member._coro)

            new: WebSocketRoute | Route

            if member._is_websocket:
                new = WebSocketRoute(path=path, endpoint=member, name=f"{name}.{member._coro.__name__}")
            else:
                new = Route(
                    path=path,
                    endpoint=member,
                    methods=member._methods,
                    name=f"{name}.{member._coro.__name__}",
                    include_in_schema=member._include_in_schema,
                )

            new.limits = getattr(member, "_limits", [])  # type: ignore
            self.__routes__.append(new)

        return self

    @property
    def prefix(self) -> str:
        return self._prefix

    @property
    def views(self) -> list[View]:
        return self._views

    def add_view(self, view: View | Self) -> None:
        if view in self._views:
            msg: str = f"A view with the name '{view.name}' has already been added to this application."
            raise RuntimeError(msg)

        routes: list[Route | WebSocketRoute] = getattr(view, "__routes__", [])

        for route_ in routes:
            path = f"/{self._prefix.lstrip('/')}{route_.path}" if self._prefix else route_.path

            if isinstance(route_, WebSocketRoute):
                new = WebSocketRoute(path, endpoint=route_.endpoint, name=route_.name)
            else:
                methods: list[str] | None = list(route_.methods) if route_.methods else None
                new = Route(
                    path,
                    endpoint=route_.endpoint,
                    methods=methods,
                    name=route_.name,
                    include_in_schema=route_.include_in_schema,
                )

            new.limits = route_.limits  # type: ignore
            self.routes.append(new)

        if isinstance(view, View):
            self._views.append(view)


class View:
    __routes__: list[Route | WebSocketRoute]
    __prefix__: ClassVar[str | None] = None

    def __init_subclass__(cls, *, prefix: str | None = None) -> None:
        cls.__prefix__ = prefix

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        self = super().__new__(cls)
        name = cls.__name__
        prefix = cls.__prefix__ or name

        self.__routes__ = []

        for _, member in inspect.getmembers(self, predicate=lambda m: isinstance(m, _Route)):
            member._view = self
            path: str = member._path

            if member._prefix:
                path = f"/{prefix.lower()}/{path.lstrip('/')}"

            for method in member._methods:
                method = method.lower()

                # Due to the way Starlette works, this allows us to have schema documentation...
                setattr(member, method, member._coro)

            new: WebSocketRoute | Route

            if member._is_websocket:
                new = WebSocketRoute(path=path, endpoint=member, name=f"{name}.{member._coro.__name__}")
            else:
                new = Route(
                    path=path,
                    endpoint=member,
                    methods=member._methods,
                    name=f"{name}.{member._coro.__name__}",
                    include_in_schema=member._include_in_schema,
                )

            new.limits = getattr(member, "_limits", [])  # type: ignore
            self.__routes__.append(new)

        return self

    @property
    def name(self) -> str:
        return self.__class__.__name__.lower()

    def __repr__(self) -> str:
        return f"View: name={self.__class__.__name__}, routes={self.__routes__}"

    def __getitem__(self, index: int) -> Route | WebSocketRoute:
        return self.__routes__[index]

    def __len__(self) -> int:
        return len(self.__routes__)

    def __iter__(self) -> Iterator[Route | WebSocketRoute]:
        return iter(self.__routes__)

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, View):
            return False

        return self.name == other.name
