"""Client-side bridge to Google's official Colab MCP server.

The upstream server remains the source of truth for browser connection,
authentication, notebook state, and execution. This module only manages its
stdio process and deliberately re-fetches its tool catalog on demand.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

LOGGER = logging.getLogger(__name__)

DEFAULT_UPSTREAM_SPEC = "git+https://github.com/googlecolab/colab-mcp.git@v1.0.2"


class GatewayError(RuntimeError):
    """Raised when the official upstream MCP server cannot be used."""


@dataclass(frozen=True, slots=True)
class RemoteTool:
    """A JSON-safe representation of an upstream MCP tool."""

    name: str
    description: str | None
    input_schema: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass(frozen=True, slots=True)
class RemoteResult:
    """A transport-neutral upstream tool result."""

    content: tuple[dict[str, Any], ...]
    structured_content: Any | None = None
    is_error: bool = False

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "content": list(self.content),
            "is_error": self.is_error,
        }
        if self.structured_content is not None:
            result["structured_content"] = self.structured_content
        return result


class ColabGateway(Protocol):
    """Operations needed by the stable compatibility surface."""

    async def list_tools(self) -> list[RemoteTool]: ...

    async def call_tool(
        self, name: str, arguments: Mapping[str, Any] | None = None
    ) -> RemoteResult: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class UpstreamConfig:
    """Safe, shell-free process configuration for Google's server."""

    command: str = "uvx"
    args: tuple[str, ...] = (DEFAULT_UPSTREAM_SPEC,)

    @classmethod
    def from_environment(cls) -> UpstreamConfig:
        command = os.environ.get("CODEX_COLAB_UPSTREAM_COMMAND", "uvx").strip()
        if not command:
            raise GatewayError("CODEX_COLAB_UPSTREAM_COMMAND cannot be empty")

        raw_args = os.environ.get("CODEX_COLAB_UPSTREAM_ARGS_JSON")
        if raw_args is None:
            spec = os.environ.get(
                "CODEX_COLAB_UPSTREAM_SPEC", DEFAULT_UPSTREAM_SPEC
            ).strip()
            if not spec:
                raise GatewayError("CODEX_COLAB_UPSTREAM_SPEC cannot be empty")
            args = (spec,)
        else:
            try:
                parsed = json.loads(raw_args)
            except json.JSONDecodeError as exc:
                raise GatewayError(
                    "CODEX_COLAB_UPSTREAM_ARGS_JSON must be a JSON string array"
                ) from exc
            if not isinstance(parsed, list) or not all(
                isinstance(item, str) for item in parsed
            ):
                raise GatewayError(
                    "CODEX_COLAB_UPSTREAM_ARGS_JSON must be a JSON string array"
                )
            args = tuple(parsed)
        return cls(command=command, args=args)


class OfficialColabGateway:
    """Lazy stdio client for the official ``googlecolab/colab-mcp`` server."""

    def __init__(self, config: UpstreamConfig | None = None) -> None:
        self._config = config or UpstreamConfig.from_environment()
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._start_lock = asyncio.Lock()

    async def _ensure_started(self) -> ClientSession:
        if self._session is not None:
            return self._session

        async with self._start_lock:
            if self._session is not None:
                return self._session

            stack = AsyncExitStack()
            try:
                params = StdioServerParameters(
                    command=self._config.command,
                    args=list(self._config.args),
                )
                read_stream, write_stream = await stack.enter_async_context(
                    stdio_client(params, errlog=sys.stderr)
                )
                session = await stack.enter_async_context(
                    ClientSession(
                        read_stream,
                        write_stream,
                        read_timeout_seconds=timedelta(seconds=180),
                    )
                )
                initialized = await session.initialize()
            except Exception as exc:
                await stack.aclose()
                raise GatewayError(
                    "Could not start Google's Colab MCP server. Ensure uv is "
                    "installed and network access is available for the first run."
                ) from exc

            self._stack = stack
            self._session = session
            server_info = initialized.serverInfo
            LOGGER.info(
                "official Colab MCP started: %s %s",
                server_info.name,
                server_info.version,
            )
            return session

    async def list_tools(self) -> list[RemoteTool]:
        session = await self._ensure_started()
        tools: list[RemoteTool] = []
        cursor: str | None = None
        try:
            while True:
                page = await session.list_tools(cursor=cursor)
                tools.extend(
                    RemoteTool(
                        name=tool.name,
                        description=tool.description,
                        input_schema=dict(tool.inputSchema),
                    )
                    for tool in page.tools
                )
                cursor = page.nextCursor
                if not cursor:
                    break
        except Exception as exc:
            raise GatewayError("Could not list tools from Google's Colab MCP") from exc
        return tools

    async def call_tool(
        self, name: str, arguments: Mapping[str, Any] | None = None
    ) -> RemoteResult:
        session = await self._ensure_started()
        try:
            result = await session.call_tool(name, dict(arguments or {}))
        except Exception as exc:
            raise GatewayError(
                f"Google's Colab MCP could not call the {name!r} tool"
            ) from exc

        content = tuple(
            item.model_dump(mode="json", by_alias=True, exclude_none=True)
            for item in result.content
        )
        return RemoteResult(
            content=content,
            structured_content=result.structuredContent,
            is_error=bool(result.isError),
        )

    async def close(self) -> None:
        async with self._start_lock:
            stack, self._stack = self._stack, None
            self._session = None
            if stack is not None:
                await stack.aclose()
