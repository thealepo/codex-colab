from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import pytest

from codex_colab.gateway import OfficialColabGateway
from codex_colab.service import ColabService

pytestmark = pytest.mark.integration


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [text for child in value.values() for text in _strings(child)]
    if isinstance(value, (list, tuple)):
        return [text for child in value for text in _strings(child)]
    return []


@pytest.mark.skipif(
    os.environ.get("COLAB_INTEGRATION") != "1",
    reason="set COLAB_INTEGRATION=1 and complete the real Colab browser flow",
)
async def test_print_two_plus_two_runs_in_real_colab() -> None:
    """Prove the result comes through Google -> browser -> runtime, not local exec."""
    service = ColabService(OfficialColabGateway())
    try:
        connection = await service.connect()
        assert connection["connected"], connection["message"]

        result = await service.execute("print(2 + 2)")
        output_lines = {
            line.strip()
            for text in _strings(result["execution"])
            for line in text.splitlines()
        }
        assert "4" in output_lines, result["execution"]
        assert result["cell_id"]
    finally:
        await service.close()
