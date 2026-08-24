import asyncio

import pytest
import pytest_socket


@pytest.fixture
def event_loop(monkeypatch: pytest.MonkeyPatch):
    """Create Windows event loops without exposing sockets to test code."""
    policy = asyncio.get_event_loop_policy()
    original_new_event_loop = policy.new_event_loop

    def create_event_loop():
        """Open the internal socket pair and restore the socket guard."""
        pytest_socket.enable_socket()
        try:
            return original_new_event_loop()
        finally:
            pytest_socket.disable_socket(allow_unix_socket=True)

    monkeypatch.setattr(policy, "new_event_loop", create_event_loop)
    loop = create_event_loop()
    setattr(loop, "__original_fixture_loop", True)
    yield loop
    loop.close()
