"""Stable, Codex-friendly operations over the dynamic upstream tool catalog."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

from codex_colab.gateway import ColabGateway, GatewayError, RemoteResult, RemoteTool

CONNECT_TOOL = "open_colab_browser_connection"
NOTEBOOK_TOOLS = {
    "add_code_cell",
    "add_text_cell",
    "delete_cell",
    "get_cells",
    "move_cell",
    "run_code_cell",
    "update_cell",
}


class ColabError(RuntimeError):
    """A user-actionable Colab adapter error."""


class ColabService:
    """Coordinates small workflows without taking ownership from upstream."""

    def __init__(self, gateway: ColabGateway) -> None:
        self._gateway = gateway
        self._operation_lock = asyncio.Lock()

    async def connect(self) -> dict[str, Any]:
        """Open Google's browser connection flow and refresh the remote catalog."""
        async with self._operation_lock:
            tools = await self._tools_by_name()
            available = sorted(name for name in tools if name != CONNECT_TOOL)
            if available:
                return {
                    "connected": True,
                    "available_tools": available,
                    "upstream_result": None,
                    "message": "The Colab browser session is already connected.",
                }
            if CONNECT_TOOL not in tools:
                raise ColabError(
                    "Google's Colab MCP did not advertise its connection tool"
                )
            result = await self._gateway.call_tool(CONNECT_TOOL, {})
            self._raise_for_result(CONNECT_TOOL, result)
            refreshed = await self._tools_by_name()

        available = sorted(name for name in refreshed if name != CONNECT_TOOL)
        return {
            "connected": bool(available),
            "available_tools": available,
            "upstream_result": result.as_dict(),
            "message": (
                "Connected to the Colab browser session."
                if available
                else "The browser connection is not ready. Complete the Colab tab "
                "connection, then call colab_connect again."
            ),
        }

    async def status(self) -> dict[str, Any]:
        """Report connection state inferred from Google's current tool catalog."""
        async with self._operation_lock:
            tools = await self._tools_by_name()
        names = sorted(tools)
        notebook_tools = sorted(name for name in NOTEBOOK_TOOLS if name in tools)
        return {
            "upstream_available": bool(names),
            "connected": bool(notebook_tools),
            "notebook_tools": notebook_tools,
            "all_upstream_tools": names,
        }

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return a fresh, JSON-safe upstream tool catalog."""
        async with self._operation_lock:
            tools = await self._gateway.list_tools()
        return [tool.as_dict() for tool in sorted(tools, key=lambda item: item.name)]

    async def call(
        self, tool_name: str, arguments: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Call one currently advertised upstream tool."""
        if tool_name == CONNECT_TOOL:
            raise ColabError("Use colab_connect for the browser connection flow")
        async with self._operation_lock:
            tools = await self._tools_by_name()
            self._require_tool(tool_name, tools)
            safe_arguments = self._fit_arguments(tools[tool_name], arguments or {})
            result = await self._gateway.call_tool(tool_name, safe_arguments)
        self._raise_for_result(tool_name, result)
        return result.as_dict()

    async def get_cells(
        self,
        *,
        start: int = 0,
        end: int | None = None,
        include_outputs: bool = True,
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            "start": start,
            "includeOutputs": include_outputs,
        }
        if end is not None:
            arguments["end"] = end
        return await self.call("get_cells", arguments)

    async def add_code_cell(
        self,
        code: str,
        *,
        cell_index: int | None = None,
        language: str = "python",
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {"code": code, "language": language}
        if cell_index is not None:
            arguments["cellIndex"] = cell_index
        return await self.call("add_code_cell", arguments)

    async def add_text_cell(
        self, content: str, *, cell_index: int | None = None
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {"content": content}
        if cell_index is not None:
            arguments["cellIndex"] = cell_index
        return await self.call("add_text_cell", arguments)

    async def update_cell(self, cell_id: str, content: str) -> dict[str, Any]:
        return await self.call("update_cell", {"cellId": cell_id, "content": content})

    async def delete_cell(self, cell_id: str) -> dict[str, Any]:
        return await self.call("delete_cell", {"cellId": cell_id})

    async def move_cell(self, cell_id: str, cell_index: int) -> dict[str, Any]:
        return await self.call(
            "move_cell", {"cellId": cell_id, "cellIndex": cell_index}
        )

    async def run_code_cell(self, cell_id: str) -> dict[str, Any]:
        return await self.call("run_code_cell", {"cellId": cell_id})

    async def execute(
        self,
        code: str,
        *,
        cell_index: int | None = None,
        language: str = "python",
    ) -> dict[str, Any]:
        """Add a visible code cell, run it in Colab, and return its remote output."""
        added = await self.add_code_cell(code, cell_index=cell_index, language=language)
        cell_id = _find_cell_id(added)
        if not cell_id:
            raise ColabError(
                "Colab added a cell but did not return a cellId; inspect the "
                "notebook with colab_get_cells before retrying"
            )
        execution = await self.run_code_cell(cell_id)
        return {"cell_id": cell_id, "added": added, "execution": execution}

    async def close(self) -> None:
        await self._gateway.close()

    async def _tools_by_name(self) -> dict[str, RemoteTool]:
        try:
            tools = await self._gateway.list_tools()
        except GatewayError as exc:
            raise ColabError(str(exc)) from exc
        return {tool.name: tool for tool in tools}

    @staticmethod
    def _require_tool(tool_name: str, tools: Mapping[str, RemoteTool]) -> None:
        if tool_name not in tools:
            raise ColabError(
                f"Colab tool {tool_name!r} is not available. Call colab_connect "
                "and complete the browser connection first."
            )

    @staticmethod
    def _fit_arguments(
        tool: RemoteTool, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        properties = tool.input_schema.get("properties")
        if not isinstance(properties, dict):
            return dict(arguments)
        return {key: value for key, value in arguments.items() if key in properties}

    @staticmethod
    def _raise_for_result(tool_name: str, result: RemoteResult) -> None:
        if result.is_error:
            raise ColabError(f"Google's Colab tool {tool_name!r} returned an error")


def _find_cell_id(value: Any) -> str | None:
    """Find a cell ID in structured data or JSON text without assuming one envelope."""
    if isinstance(value, Mapping):
        for key in ("cell_id", "cellId"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
        for child in value.values():
            candidate = _find_cell_id(child)
            if candidate:
                return candidate
    elif isinstance(value, (list, tuple)):
        for child in value:
            candidate = _find_cell_id(child)
            if candidate:
                return candidate
    elif isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return None
        return _find_cell_id(decoded)
    return None
