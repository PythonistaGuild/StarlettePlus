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

import base64
import copy
import datetime
import hashlib
import json
import logging
import secrets
from typing import TYPE_CHECKING, Any

import itsdangerous
from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection

from ..redis import Redis


if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

    from ..redis import Redis


logger: logging.Logger = logging.getLogger(__name__)


class Storage:
    __slots__ = ("redis", "_keys")

    def __init__(self, *, redis: Redis | None = None) -> None:
        self.redis: Redis | None = redis
        self._keys: dict[str, Any] = {}

    async def get(self, data: dict[str, Any]) -> dict[str, Any]:
        expiry: datetime.datetime = datetime.datetime.fromisoformat(data["expiry"])
        key: str = data["_session_secret_key"]

        if expiry <= datetime.datetime.now():
            await self.delete(key)
            return {}

        if self.redis and self.redis.could_connect:
            session: Any = await self.redis.pool.get(key)  # type: ignore
        else:
            session: Any = self._keys.get(key)

        return json.loads(session) if session else {}

    async def set(self, key: str, value: dict[str, Any], *, max_age: int) -> None:
        if self.redis and self.redis.could_connect:
            await self.redis.pool.set(key, json.dumps(value), ex=max_age)  # type: ignore
            return

        self._keys[key] = json.dumps(value)

    async def delete(self, key: str) -> None:
        if self.redis and self.redis.could_connect:
            await self.redis.pool.delete(key)  # type: ignore
        else:
            self._keys.pop(key, None)


class SessionMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        name: str | None = None,
        secret: str | None = None,
        max_age: int | None = None,
        same_site: str = "lax",
        secure: bool = True,
        redis: Redis | None = None,
    ) -> None:
        self.app: ASGIApp = app
        self.name: str = name or "__session_cookie"
        self.secret: str = secret or secrets.token_urlsafe(
            128
        )  # set this if you don't want to invalidate sessions on restart
        self.max_age: int = max_age or (60 * 60 * 24 * 7)  # 7 days; 1 week
        self.signing: itsdangerous.Signer = itsdangerous.Signer(self.secret, digest_method=hashlib.sha256)
        self.storage: Storage = Storage(redis=redis)

        self.flags: str = f"HttpOnly; SameSite={same_site}; Path=/{'; secure' if secure else ''}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # Use this to cover both websocket connections and http connections
        connection: HTTPConnection = HTTPConnection(scope, receive)
        session: dict[str, Any]

        try:
            cookie: bytes = connection.cookies[self.name].encode("utf-8")
        except KeyError:
            cookie = b""

        try:
            unsigned: str = self.signing.unsign(base64.b64decode(cookie)).decode("utf-8")
            data: dict[str, Any] = json.loads(unsigned)
            session = await self.storage.get(data)
        except (KeyError, itsdangerous.BadSignature):
            session = {}

        original: dict[str, Any] = copy.deepcopy(session)
        scope["session"] = session

        async def wrapper(message: Message) -> None:
            nonlocal original, session, cookie

            if message["type"] != "http.response.start":
                await send(message)
                return

            headers: MutableHeaders = MutableHeaders(scope=message)
            secret_key: str = scope["session"].get("_session_secret_key", secrets.token_urlsafe(64))

            # At this point we can assume that the server has cleared the session...
            if not scope["session"] and original:
                await self.storage.delete(original["_session_secret_key"])
                headers.append("Set-Cookie", self.cookies(value="null", clear=True))

            # Server has updated the session data so we need to set a new cookie...
            elif scope["session"] != original:
                expiry = datetime.datetime.now() + datetime.timedelta(seconds=self.max_age)
                scope["session"]["_session_secret_key"] = secret_key

                cookie_: dict[str, str] = {"_session_secret_key": secret_key, "expiry": expiry.isoformat()}
                signed: bytes = base64.b64encode(self.signing.sign(json.dumps(cookie_)))
                headers.append("Set-Cookie", self.cookies(value=signed.decode("utf-8")))

                await self.storage.set(secret_key, scope["session"], max_age=self.max_age)

            elif not session and not original and cookie:
                headers.append("Set-Cookie", self.cookies(value="null", clear=True))

            await send(message)

        await self.app(scope, receive, wrapper)

    def cookies(self, *, value: str, clear: bool = False) -> str:
        if clear:
            return f"{self.name}={value}; {self.flags}; Max-Age=0"

        return f"{self.name}={value}; {self.flags}; Max-Age={self.max_age}"
