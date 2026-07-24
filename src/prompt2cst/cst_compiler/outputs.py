from __future__ import annotations


def compile_requested_outputs(outputs: list[str]) -> str:
    # Requested outputs are metadata until a solver execution is separately approved.
    return "\n".join(f"' Requested output: {item}" for item in sorted(outputs))
