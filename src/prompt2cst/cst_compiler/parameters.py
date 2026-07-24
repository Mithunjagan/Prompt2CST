from __future__ import annotations

from .common import format_number, history_string


def compile_parameters(parameters: dict[str, float]) -> str:
    return "\n".join(
        f'StoreParameter "{history_string(name)}", "{format_number(value)}"'
        for name, value in sorted(parameters.items())
    )
