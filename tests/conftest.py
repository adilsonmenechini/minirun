from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def patch_asyncio_sleep() -> Generator[None, None, None]:
    patcher = patch("minirun.ports.provider.asyncio.sleep", AsyncMock())
    patcher.start()
    yield
    patcher.stop()
