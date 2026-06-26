"""Progress reporting helpers."""


def log(message: str) -> None:
    """Print one progress message immediately."""
    print(message, flush=True)
