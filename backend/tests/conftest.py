
import pytest

from starlette.testclient import TestClient


@pytest.fixture(autouse=True)
def use_valid_test_client_ip(monkeypatch):
    """
    Give tests a valid client IP by default.

    Explicit client addresses supplied by individual tests
    are preserved.
    """
    original_init = TestClient.__init__

    def init_with_test_ip(self, *args, **kwargs):
        kwargs.setdefault("client", ("192.0.2.10", 50000))
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(
        TestClient,
        "__init__",
        init_with_test_ip,
    )
