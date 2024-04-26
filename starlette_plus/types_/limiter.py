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

from collections.abc import Awaitable, Callable
from typing import Literal, NotRequired, TypeAlias, TypedDict

from starlette.requests import Request
from starlette.responses import Response


BucketCallable: TypeAlias = Callable[[Request], Awaitable[str | None]]
ExemptCallable: TypeAlias = Callable[[Request], Awaitable[bool]]

BucketType: TypeAlias = Literal["ip"] | BucketCallable
ResponseCallback: TypeAlias = Callable[[Request, float], Awaitable[Response]]


class RateLimitData(TypedDict):
    rate: int
    per: float
    bucket: NotRequired[BucketType]
    priority: NotRequired[int]
    exempt: NotRequired[ExemptCallable | None]
    is_global: NotRequired[bool]
