#!/usr/bin/env python3
# GUTTED 2026-04-09 — Guardian SessionStart hook permanently disabled.
# Preserved as a no-op to avoid import errors. Do not re-enable.
import sys


def build_summary(*args, **kwargs) -> str:
    return ""


def main() -> int:
    return 0


if __name__ == "__main__":
    sys.exit(main())
