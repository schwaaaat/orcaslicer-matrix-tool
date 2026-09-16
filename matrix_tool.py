#!/usr/bin/env python3
"""OrcaSlicer Matrix Studio executable entrypoint."""

import sys


def main() -> int:
    # Preserve the legacy command surface for scripted runs during the v2 transition.
    # A plain launch opens the new Matrix Studio desktop application.
    if len(sys.argv) > 1 and sys.argv[1] not in {"--studio"}:
        from orcaslicer_matrix.cli import main as cli_main

        return cli_main()

    from orcaslicer_matrix.studio import main as studio_main

    args = sys.argv[2:] if len(sys.argv) > 1 else []
    return studio_main(args)

if __name__ == "__main__":
    sys.exit(main())
