"""Value checks shared by the configuration and the engine data."""

from math import isfinite


def check_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty identifier")


def check_quantity(name: str, value: float, *, positive: bool = False) -> None:
    if not isfinite(value) or value < 0 or (positive and value == 0):
        bound = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be finite and {bound}")
