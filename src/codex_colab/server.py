"""Static MCP tool surface for Codex backed by Google's dynamic Colab MCP."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from codex_colab.gateway import OfficialColabGateway
from codex_colab.service import ColabService


@asynccontextmanager
async def lifespan(_: FastMCP):
    service = ColabService(OfficialColabGateway())
    try:
        yield {"service": service}
    finally:
        await service.close()


mcp = FastMCP(
    "Codex Colab",
    instructions=(
        "Connect before notebook work. Inspect cells before editing. The tools "
        "operate on a real Google Colab tab and can execute arbitrary code."
    ),
    lifespan=lifespan,
)

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
ADDITIVE_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
MUTATING_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)
ARBITRARY_EXECUTION = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)


def _service(ctx: Context) -> ColabService:
    return ctx.request_context.lifespan_context["service"]


@mcp.tool(annotations=ADDITIVE_WRITE)
async def colab_connect(ctx: Context) -> dict[str, Any]:
    """Open Google's Colab browser flow and connect the current local session."""
    return await _service(ctx).connect()


@mcp.tool(annotations=READ_ONLY)
async def colab_status(ctx: Context) -> dict[str, Any]:
    """Check whether the official server and notebook tools are available."""
    return await _service(ctx).status()


@mcp.tool(annotations=READ_ONLY)
async def colab_list_tools(ctx: Context) -> list[dict[str, Any]]:
    """Fetch the current official Colab tool catalog and input schemas."""
    return await _service(ctx).list_tools()


@mcp.tool(annotations=READ_ONLY)
async def colab_get_cells(
    ctx: Context,
    start: int = 0,
    end: int | None = None,
    include_outputs: bool = True,
) -> dict[str, Any]:
    """Read notebook cells and, by default, their current execution outputs."""
    return await _service(ctx).get_cells(
        start=start, end=end, include_outputs=include_outputs
    )


@mcp.tool(annotations=ADDITIVE_WRITE)
async def colab_add_code_cell(
    code: str,
    ctx: Context,
    cell_index: int | None = None,
    language: str = "python",
) -> dict[str, Any]:
    """Insert a visible code cell without executing it."""
    return await _service(ctx).add_code_cell(
        code, cell_index=cell_index, language=language
    )


@mcp.tool(annotations=ADDITIVE_WRITE)
async def colab_add_text_cell(
    content: str, ctx: Context, cell_index: int | None = None
) -> dict[str, Any]:
    """Insert a visible Markdown/text cell without executing code."""
    return await _service(ctx).add_text_cell(content, cell_index=cell_index)


@mcp.tool(annotations=MUTATING_WRITE)
async def colab_update_cell(cell_id: str, content: str, ctx: Context) -> dict[str, Any]:
    """Replace one existing cell's content; its prior content may be lost."""
    return await _service(ctx).update_cell(cell_id, content)


@mcp.tool(annotations=MUTATING_WRITE)
async def colab_delete_cell(cell_id: str, ctx: Context) -> dict[str, Any]:
    """Delete one existing notebook cell."""
    return await _service(ctx).delete_cell(cell_id)


@mcp.tool(annotations=MUTATING_WRITE)
async def colab_move_cell(
    cell_id: str, cell_index: int, ctx: Context
) -> dict[str, Any]:
    """Move one existing cell to a new zero-based notebook position."""
    return await _service(ctx).move_cell(cell_id, cell_index)


@mcp.tool(annotations=ARBITRARY_EXECUTION)
async def colab_run_code_cell(cell_id: str, ctx: Context) -> dict[str, Any]:
    """Execute an existing code cell in the connected Colab runtime."""
    return await _service(ctx).run_code_cell(cell_id)


@mcp.tool(annotations=ARBITRARY_EXECUTION)
async def colab_execute(
    code: str,
    ctx: Context,
    cell_index: int | None = None,
    language: str = "python",
) -> dict[str, Any]:
    """Add a visible code cell, execute it in Colab, and return remote output."""
    return await _service(ctx).execute(code, cell_index=cell_index, language=language)


@mcp.tool(annotations=ARBITRARY_EXECUTION)
async def colab_call_tool(
    tool_name: str, arguments: dict[str, Any], ctx: Context
) -> dict[str, Any]:
    """Call any currently advertised official Colab tool with explicit arguments."""
    return await _service(ctx).call(tool_name, arguments)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
