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

import uvicorn
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import Response

import starlette_plus


class App(starlette_plus.Application):
    def __init__(self) -> None:
        # Add the ratelimiter middleware to the application
        # This allows global and per-route rate limiting
        # You can use this with Redis or in-memory storage
        ratelimiter = Middleware(starlette_plus.middleware.RatelimitMiddleware)

        # We set a prefix which means all routes will be prefixed with /v1
        super().__init__(prefix="/v1", middleware=[ratelimiter], access_log=True)

    @starlette_plus.route("/", methods=["GET"])
    # This route is limited to 1 request per 60 seconds
    # Decorator order with starlette_plus shouldn't matter
    # You can put the limit decorator on-top or below the route decorator
    @starlette_plus.limit(1, 60)
    async def home(self, request: Request) -> Response:
        # Visit http://localhost:8000/v1/ to see this route...

        return starlette_plus.JSONResponse({"message": "Hello, World!"})


async def main() -> None:
    # This is completely optional
    # This is a helper function to setup logging
    starlette_plus.setup_logging(level=20, root=True)
    app: App = App()

    # This is the uvicorn configuration
    # You can change the host and port to whatever you want
    # We set access_log to False to disable uvicorn access logging, since we set this on our Application
    config: uvicorn.Config = uvicorn.Config(app=app, host="localhost", port=8000, access_log=False)
    server: uvicorn.Server = uvicorn.Server(config)

    await server.serve()


asyncio.run(main())
