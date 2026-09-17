#!/usr/bin/env python3
"""OrcaSlicer Matrix Studio executable entrypoint."""

import sys


def studio_arguments(argv: list[str]) -> list[str] | None:
    """Return Studio arguments, or None when the legacy CLI owns the launch."""
    if not argv:
        return []
    if argv[0] == "--studio":
        return argv[1:]
    if any(arg == "--connect" or arg.startswith("--connect=") for arg in argv):
        return argv
    return None


def main() -> int:
    # Preserve the legacy command surface for scripted runs during the v2 transition.
    # A plain launch opens the new Matrix Studio desktop application.
    studio_args = studio_arguments(sys.argv[1:])
    if studio_args is None:
        from orcaslicer_matrix.cli import main as cli_main

        return cli_main()

    from orcaslicer_matrix.studio import main as studio_main

    return studio_main(studio_args)

if __name__ == "__main__":
    sys.exit(main())
