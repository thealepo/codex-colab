from __future__ import annotations

import pytest
from conftest import FakeGateway

from codex_colab.service import CONNECT_TOOL, NOTEBOOK_TOOLS, ColabError


async def test_status_is_disconnected_before_browser_connection(service) -> None:
    status = await service.status()

    assert status == {
        "upstream_available": True,
        "connected": False,
        "notebook_tools": [],
        "all_upstream_tools": [CONNECT_TOOL],
    }


async def test_connect_explicitly_refreshes_dynamic_upstream_tools(
    service, gateway: FakeGateway
) -> None:
    result = await service.connect()

    assert result["connected"] is True
    assert result["available_tools"] == sorted(NOTEBOOK_TOOLS)
    assert gateway.calls == [(CONNECT_TOOL, {})]


async def test_connect_is_safe_to_repeat_after_browser_connection(
    service, gateway: FakeGateway
) -> None:
    gateway.connected = True

    result = await service.connect()

    assert result["connected"] is True
    assert result["upstream_result"] is None
    assert result["message"] == "The Colab browser session is already connected."
    assert gateway.calls == []


async def test_status_reports_upstream_available_after_browser_connection(
    service, gateway: FakeGateway
) -> None:
    gateway.connected = True

    status = await service.status()

    assert status["upstream_available"] is True
    assert status["connected"] is True


async def test_get_cells_maps_python_names_to_official_schema(
    service, gateway: FakeGateway
) -> None:
    gateway.connected = True

    await service.get_cells(start=2, end=5, include_outputs=False)

    assert gateway.calls[-1] == (
        "get_cells",
        {"start": 2, "end": 5, "includeOutputs": False},
    )


async def test_known_tool_wrappers_forward_without_reimplementing_colab(
    service, gateway: FakeGateway
) -> None:
    gateway.connected = True

    await service.add_code_cell("x = 1", cell_index=3, language="python")
    await service.add_text_cell("# Heading", cell_index=0)
    await service.update_cell("c1", "x = 2")
    await service.delete_cell("c2")
    await service.move_cell("c3", 4)
    await service.run_code_cell("c4")

    assert gateway.calls == [
        (
            "add_code_cell",
            {"code": "x = 1", "language": "python", "cellIndex": 3},
        ),
        ("add_text_cell", {"content": "# Heading", "cellIndex": 0}),
        ("update_cell", {"cellId": "c1", "content": "x = 2"}),
        ("delete_cell", {"cellId": "c2"}),
        ("move_cell", {"cellId": "c3", "cellIndex": 4}),
        ("run_code_cell", {"cellId": "c4"}),
    ]


async def test_generic_call_drops_arguments_not_in_live_upstream_schema(
    service, gateway: FakeGateway
) -> None:
    gateway.connected = True

    await service.call("run_code_cell", {"cellId": "c1", "unexpected": "not forwarded"})

    assert gateway.calls[-1] == ("run_code_cell", {"cellId": "c1"})


async def test_unavailable_tool_has_connection_guidance(service) -> None:
    with pytest.raises(ColabError, match="Call colab_connect"):
        await service.get_cells()


async def test_execute_adds_and_runs_a_cell_in_the_remote_workflow(
    service, gateway: FakeGateway
) -> None:
    gateway.connected = True

    result = await service.execute("print(2 + 2)")

    assert result["cell_id"] == "cell-42"
    assert result["execution"]["structured_content"]["outputs"][0]["text"] == ["4\n"]
    assert gateway.calls == [
        ("add_code_cell", {"code": "print(2 + 2)", "language": "python"}),
        ("run_code_cell", {"cellId": "cell-42"}),
    ]


async def test_close_delegates_to_gateway(service, gateway: FakeGateway) -> None:
    await service.close()

    assert gateway.closed is True
