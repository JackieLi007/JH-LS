"""Backend package for the merged Flask services."""


def create_app():
    from backend.app import create_app as _create_app

    return _create_app()
