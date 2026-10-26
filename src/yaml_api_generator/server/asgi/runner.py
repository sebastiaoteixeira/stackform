import json
import re
from typing import Any
from urllib.parse import parse_qs

from yaml_api_generator.ir import IRDocument
from yaml_api_generator.runtime.lifecycle import Purger
from ..common.server_context import RuntimeContext, RuntimeRouteDescriptor
from ..common.loader import initialize_indexes
from ..common.pipeline import Pipeline
from ..common.pipeline_builder import PipelineBuilder
from ..common.repositories import RepositoryRegistry
from ..common.steps import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError


_RouteEntry = tuple[re.Pattern[str], Pipeline, RuntimeRouteDescriptor]


def _compile_path(path: str) -> re.Pattern[str]:
    regex = "".join(
        f"(?P<{part[1:-1]}>[^/]+)" if part.startswith("{") else re.escape(part)
        for part in re.split(r"(\{\w+\})", path)
    )
    return re.compile(f"^{regex}$")


class ASGIApp:
    def __init__(self, ctx: RuntimeContext, registry: RepositoryRegistry, ir: IRDocument | None = None) -> None:
        self._registry = registry
        self._ir = ir
        self._purger = Purger(repository.purge_expired for repository in registry.all())
        self._routes: dict[str, list[_RouteEntry]] = {}
        builder = PipelineBuilder(ctx=ctx, registry=registry)

        for route in ctx.routes:
            pipeline = builder.build_for_route(route)
            pattern = _compile_path(route.path)
            entry: _RouteEntry = (pattern, pipeline, route)
            self._routes.setdefault(route.method.upper(), []).append(entry)

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
    ) -> None:
        if scope["type"] == "lifespan":
            await self._handle_lifespan(scope, receive, send)
            return

        if scope["type"] == "http":
            await self._handle_http(scope, receive, send)
            return

    async def _handle_lifespan(
        self, scope: dict[str, Any], receive: Any, send: Any,
    ) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                if self._ir is not None:
                    await initialize_indexes(self._ir, self._registry)
                self._purger.start()
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await self._purger.stop()
                for repository in self._registry.all():
                    await repository.close()
                await send({"type": "lifespan.shutdown.complete"})
                return

    async def _handle_http(
        self, scope: dict[str, Any], receive: Any, send: Any,
    ) -> None:
        method = scope["method"].upper()
        path = scope["path"]

        pipeline, route, url_params = self._match_route(method, path)
        if pipeline is None:
            await self._send_json(send, 404, {"detail": "Not found"})
            return

        try:
            body = await self._read_body(receive)
        except (json.JSONDecodeError, UnicodeDecodeError):
            await self._send_json(send, 400, {"detail": "Invalid JSON body"})
            return

        headers = {
            k.decode("latin-1"): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }

        query = parse_qs(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)

        try:
            ctx = await pipeline.run(
                headers=headers,
                url_params=url_params,
                body=body,
                query=query,
            )
        except UnauthorizedError as exc:
            await self._send_json(send, 401, {"detail": str(exc)})
            return
        except ForbiddenError as exc:
            await self._send_json(send, 403, {"detail": str(exc)})
            return
        except NotFoundError as exc:
            await self._send_json(send, 404, {"detail": str(exc)})
            return
        except ConflictError as exc:
            await self._send_json(send, 409, {"detail": str(exc)})
            return
        except ValueError as exc:
            await self._send_json(send, 422, {"detail": str(exc)})
            return

        await self._send_json(send, 200, ctx.response)

    def _match_route(
        self, method: str, path: str,
    ) -> tuple[Pipeline | None, RuntimeRouteDescriptor | None, dict[str, str]]:
        entries = self._routes.get(method, [])
        for pattern, pipeline, route in entries:
            match = pattern.match(path)
            if match:
                return pipeline, route, match.groupdict()
        return None, None, {}

    @staticmethod
    async def _read_body(receive: Any) -> dict[str, Any] | None:
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
        if not body:
            return None
        return json.loads(body)

    @staticmethod
    async def _send_json(send: Any, status: int, data: Any) -> None:
        body = json.dumps(data, default=str).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                [b"content-type", b"application/json"],
                [b"content-length", str(len(body)).encode("latin-1")],
            ],
        })
        await send({"type": "http.response.body", "body": body})

