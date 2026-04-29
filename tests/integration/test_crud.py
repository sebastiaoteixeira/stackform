import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Requires running MongoDB and server")
def test_list_returns_empty() -> None:
    pass


@pytest.mark.skip(reason="Requires running MongoDB and server")
def test_create_and_get() -> None:
    pass
