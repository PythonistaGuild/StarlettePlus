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
import random

import uvicorn

import starlette_plus


class APIView(starlette_plus.View, prefix="api"):
    # By default all routes in a View are prefixed with the Views class name...
    # We have two options to control this:
    # 1.) We can set a custom prefix on the View as shown above with the prefix="api" keyword-argument.
    # 2.) Routes can disable the prefix by passing prefix=False to the route decorator.
    # If we didn't set the prefix="api" the prefix for this View would be "/apiview"

    def __init__(self, app: App) -> None:
        # This is our App class we make below...
        # We pass this to the view when we create it...
        self.app: App = app

        self.some_state: str = "Some cool thing only I know!"

    @starlette_plus.route("/random", methods=["GET"])
    # Remember: This route has a View prefix, so the full path is /api/random
    async def random_roll(self, request: starlette_plus.Request) -> starlette_plus.Response:
        return starlette_plus.JSONResponse({"roll": random.randint(1, 100)})

    @starlette_plus.route("/test", methods=["GET"], prefix=False)
    # This route does NOT have a view prefix, so the full route is just: /test
    async def test_route(self, request: starlette_plus.Request) -> starlette_plus.Response:
        # One of the benefits of having the option to disable the prefix is being able to place routes in classes
        # that contain similar functions or state that may be required
        return starlette_plus.Response(f"Hello from APIView: {self.some_state}")


class App(starlette_plus.Application):
    def __init__(self) -> None:
        # Add our View:
        # You can put and contain views in their own files, and import them
        # We pass this application to our View, this is optional but often useful.
        super().__init__(access_log=True, views=[APIView(self)])

    @starlette_plus.route("/")
    async def home(self, request: starlette_plus.Request) -> starlette_plus.Response:
        return starlette_plus.HTMLResponse("""<a href="/test">/test</a><br/><a href="/api/random">/api/random</a>""")


async def main() -> None:
    starlette_plus.setup_logging(level=20, root=True)
    app: App = App()

    config: uvicorn.Config = uvicorn.Config(app=app, host="localhost", port=8000, access_log=False)
    server: uvicorn.Server = uvicorn.Server(config)

    await server.serve()


asyncio.run(main())
