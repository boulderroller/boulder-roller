"""Backend application package for BoulderRollers v2."""

__all__ = ["create_app"]


def create_app():
    # Lazily import to avoid side effects during module import (e.g., in tests)
    from .main import create_app as _create_app

    return _create_app()
