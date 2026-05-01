import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Requires running MongoDB and server")
def test_register_user() -> None:
    pass


@pytest.mark.skip(reason="Requires running MongoDB and server")
def test_login_user() -> None:
    pass
