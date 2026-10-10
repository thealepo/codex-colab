from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from codex_colab.gateway import RemoteResult, RemoteTool
from codex_colab.service import CONNECT_TOOL, NOTEBOOK_TOOLS, ColabService


def _schema(*names: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {name: {} for name in names},
        "additionalProperties": False,
    }


TOOL_SCHEMAS = {
    CONNECT_TOOL: _schema(),
    "get_cells": _schema("start", "end", "includeOutputs"),
    "add_code_cell": _schema("cellIndex", "language", "code"),
    "add_text_cell": _schema("cellIndex", "content"),
    "update_cell": _schema("cellId", "content"),
    "delete_cell": _schema("cellId"),
    "move_cell": _schema("cellId", "cellIndex"),
    "run_code_cell": _schema("cellId"),
}


class FakeGateway:
    def __init__(self, *, connected: bool = False) -> None:
        self.connected = connected
        self.closed = False
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[RemoteTool]:
        names = {CONNECT_TOOL}
        if self.connected:
            names |= NOTEBOOK_TOOLS
        return [
            RemoteTool(name, f"Description for {name}", TOOL_SCHEMAS[name])
            for name in sorted(names)
        ]

    async def call_tool(
        self, name: str, arguments: Mapping[str, Any] | None = None
    ) -> RemoteResult:
        values = dict(arguments or {})
        self.calls.append((name, values))
        if name == CONNECT_TOOL:
            self.connected = True
            return RemoteResult(
                content=({"type": "text", "text": "true"},),
                structured_content={"result": True},
            )
        if name == "add_code_cell":
            return RemoteResult(
                content=({"type": "text", "text": '{"cellId":"cell-42"}'},),
                structured_content={"cellId": "cell-42"},
            )
        if name == "run_code_cell":
            return RemoteResult(
                content=({"type": "text", "text": "4\n"},),
                structured_content={
                    "outputs": [
                        {
                            "output_type": "stream",
                            "name": "stdout",
                            "text": ["4\n"],
                        }
                    ]
                },
            )
        return RemoteResult(content=({"type": "text", "text": "ok"},))

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def service(gateway: FakeGateway) -> ColabService:
    return ColabService(gateway)
