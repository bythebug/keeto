import pytest

from keeto.core.monitor import Monitor
from keeto.storage.memory import MemoryStorage


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage(max_traces=100)


@pytest.fixture
def monitor(storage: MemoryStorage) -> Monitor:
    m = Monitor(storage=storage, auto=False)
    m.start()
    yield m
    m.stop()
