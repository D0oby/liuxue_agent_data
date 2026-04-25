from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re


NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def parse_duration(raw: str | float | int) -> tuple[float, float, str]:
    raw_text = str(raw).strip()
    if not raw_text:
        raise ValueError("Duration cannot be empty")

    parts = NUMBER_RE.findall(raw_text)
    if not parts:
        raise ValueError(f"Unsupported duration format: {raw_text}")

    try:
        numbers = [Decimal(part) for part in parts]
    except InvalidOperation as exc:  # pragma: no cover
        raise ValueError(f"Invalid duration value: {raw_text}") from exc

    if len(numbers) == 1:
        value = float(numbers[0])
        return value, value, raw_text

    if len(numbers) == 2:
        left, right = sorted(float(number) for number in numbers)
        return left, right, raw_text

    raise ValueError(f"Unsupported duration format: {raw_text}")

