#!/usr/bin/env python3
"""Small source-tree wrapper for ``robot-brain batch-compile``.

Keeping this wrapper makes the compiler convenient in CI and from a checkout;
the installed console entry point remains the canonical interface.
"""

from robot_agent_brain.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["batch-compile", *__import__("sys").argv[1:]]))
