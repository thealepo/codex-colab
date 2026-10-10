from __future__ import annotations

from codex_colab.server import mcp

EXPECTED_TOOLS = {
    "colab_add_code_cell",
    "colab_add_text_cell",
    "colab_call_tool",
    "colab_connect",
    "colab_delete_cell",
    "colab_execute",
    "colab_get_cells",
    "colab_list_tools",
    "colab_move_cell",
    "colab_run_code_cell",
    "colab_status",
    "colab_update_cell",
}


async def test_static_tool_catalog_is_available_before_colab_connects() -> None:
    tools = {tool.name: tool for tool in await mcp.list_tools()}

    assert set(tools) == EXPECTED_TOOLS
    assert tools["colab_status"].annotations.readOnlyHint is True
    assert tools["colab_get_cells"].annotations.readOnlyHint is True
    assert tools["colab_execute"].annotations.openWorldHint is True
    assert tools["colab_execute"].annotations.destructiveHint is True
    assert tools["colab_delete_cell"].annotations.destructiveHint is True


async def test_execute_schema_requires_code_but_not_context() -> None:
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    schema = tools["colab_execute"].inputSchema

    assert schema["required"] == ["code"]
    assert "ctx" not in schema["properties"]
