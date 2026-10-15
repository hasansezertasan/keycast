"""Smoke tests for keycast package."""


def test_smoke() -> None:
    """Test that the package can be imported."""
    import keycast

    assert keycast is not None
