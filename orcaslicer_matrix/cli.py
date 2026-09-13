"""CLI entrypoint for OrcaSlicer matrix tool.

Parses command line arguments, coordinates runner execution, and optionally launches
the compare viewer.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

from .client import OrcaAuthError, OrcaClient, OrcaConnectionError, OrcaError
from .matrix import (
    MAX_DIMENSIONS,
    MAX_VARIANTS,
    DimensionLimitExceededError,
    VariantLimitExceededError,
    build_variants,
    parse_matrix_input,
)
from .runner import MatrixRunner
from .schema import UnknownSettingError


KNOWN_VIEWER_LOCATIONS = [
    Path(r"C:\Users\Justin\Apps\OrcaSlicer-MCP\orca-slicer.exe"),
    Path(r"G:\Claude\OrcaBuild\OrcaSlicer-VFjr-package\OrcaSlicer-VFjr\orca-slicer.exe"),
    Path(r"G:\Claude\OrcaBuild\OrcaSlicer-VFjr\build\src\Release\orca-slicer.exe"),
    Path(r"C:\Program Files\OrcaSlicer\orca-slicer.exe"),
]


def find_viewer_executable(explicit_path: Optional[str | Path]) -> Optional[Path]:
    """Locate the OrcaSlicer executable for compare mode launch."""
    if explicit_path:
        p = Path(explicit_path)
        if p.is_file():
            return p
        return None

    # Check known paths
    for candidate in KNOWN_VIEWER_LOCATIONS:
        if candidate.is_file():
            return candidate

    # Check PATH
    for cmd in ["orca-slicer", "OrcaSlicer", "orca_slicer"]:
        which_path = shutil.which(cmd)
        if which_path and Path(which_path).is_file():
            return Path(which_path)

    return None


def launch_compare_viewer(viewer_path: Path, manifest_path: Path) -> None:
    """Launch OrcaSlicer in compare mode with the generated manifest.

    Fails gracefully if the --compare flag is not supported yet by the binary.
    """
    cmd = [str(viewer_path), "--compare", str(manifest_path.resolve())]
    print(f"\nLaunching compare viewer: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Give it a moment to check for immediate startup flag rejection
        time.sleep(1.0)
        ret = proc.poll()
        if ret is not None and ret != 0:
            stderr_out = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
            print(
                f"[NOTE] OrcaSlicer exited immediately with code {ret}.\n"
                f"The '--compare' flag may not yet be implemented in this build.\n"
                f"Details: {stderr_out.strip()}"
            )
        else:
            print(f"Compare viewer running (PID {proc.pid}).")
    except Exception as e:
        print(f"[NOTE] Could not launch compare viewer ({e}).")


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orcaslicer-matrix",
        description=(
            "Standalone, token-free matrix slicer for OrcaSlicer. "
            "Slices setting permutations against current plater and produces a manifest.json "
            "for the side-by-side compare viewer."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # Slice a 2x2 matrix using CLI flags:
  python matrix_tool.py -a "layer_height=0.16,0.20" -a "wall_loops=2,3"

  # Using human-friendly labels:
  python matrix_tool.py -a "layer height=0.16,0.20" -a "wall count=2,3"

  # Slice from JSON configuration file:
  python matrix_tool.py --config my_matrix.json -o ./my_compare_run

  # Non-interactive script run bypassing ETA confirmation:
  python matrix_tool.py --config my_matrix.json --yes

  # Dry run to test setting resolution and inspect permutation count:
  python matrix_tool.py -a "layer_height=0.16,0.20,0.24" -a "wall_loops=2,3" --dry-run
""",
    )

    # Matrix input arguments (at least one is required)
    input_group = parser.add_argument_group("Matrix Definition (specify at least one)")
    input_group.add_argument(
        "config_file_pos",
        nargs="?",
        metavar="CONFIG_FILE",
        help="Path to JSON file containing matrix definition.",
    )
    input_group.add_argument(
        "-c", "--config",
        dest="config_file",
        metavar="FILE",
        help="Path to JSON file containing matrix definition.",
    )
    input_group.add_argument(
        "-m", "--matrix",
        dest="matrix_json",
        metavar="JSON_STRING",
        help='Raw JSON string mapping axes to lists of values, e.g. \'{"layer_height":["0.16","0.20"]}\'',
    )
    input_group.add_argument(
        "-a", "--axis",
        action="append",
        dest="axis_args",
        metavar="AXIS=V1,V2,...",
        help="Define an axis and its comma-separated values, e.g. -a 'layer_height=0.16,0.20'. Can be repeated.",
    )

    # Output options
    out_group = parser.add_argument_group("Output Options")
    out_group.add_argument(
        "-o", "--output-dir",
        default="./compare_output",
        help="Directory to write G-code files and manifest.json (default: ./compare_output).",
    )
    out_group.add_argument(
        "--baseline",
        metavar="NAME",
        help="Name of baseline variant in manifest (defaults to first variant).",
    )

    # Connection options
    conn_group = parser.add_argument_group("OrcaSlicer Connection")
    conn_group.add_argument(
        "--url",
        default=None,
        help="OrcaSlicer Remote API base URL (default: http://127.0.0.1:13130 or ORCA_API_URL).",
    )
    conn_group.add_argument(
        "--token",
        default=None,
        help="API token (defaults to ORCA_API_TOKEN env var, or read from OrcaSlicer.conf).",
    )
    conn_group.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Timeout in seconds for each slice operation (default: 300).",
    )

    # Execution control
    exec_group = parser.add_argument_group("Execution Control")
    exec_group.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Non-interactive mode: skip confirmation prompt after baseline slice ETA calculation.",
    )
    exec_group.add_argument(
        "--auto-confirm-under",
        type=float,
        default=30.0,
        metavar="SECONDS",
        help="Auto-skip confirmation if total estimated slicing time is under this threshold in seconds (default: 30.0). Set to 0 to always prompt.",
    )
    exec_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve settings, check permutation count, snapshot plater, and exit without slicing.",
    )

    # Viewer launch
    viewer_group = parser.add_argument_group("Compare Viewer Integration")
    viewer_group.add_argument(
        "--launch-viewer",
        action="store_true",
        help="Automatically launch OrcaSlicer in compare mode after slicing completes.",
    )
    viewer_group.add_argument(
        "--viewer-path",
        metavar="EXE_PATH",
        help="Explicit path to orca-slicer.exe for --launch-viewer.",
    )

    # Graphical User Interface
    gui_group = parser.add_argument_group("Graphical User Interface")
    gui_group.add_argument(
        "--gui",
        action="store_true",
        help="Launch the interactive desktop Graphical User Interface.",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.gui:
        from .gui import launch_gui
        return launch_gui()

    config_file = args.config_file or args.config_file_pos
    if not config_file and not args.matrix_json and not args.axis_args:
        # If invoked without any CLI args, launch the GUI for convenience
        if argv is None and len(sys.argv) == 1:
            from .gui import launch_gui
            return launch_gui()
        parser.print_help()
        print("\nError: Please provide a matrix definition via --config, --matrix, or --axis (or use --gui).")
        return 1

    try:
        # 1. Parse and validate matrix definition
        resolved_matrix = parse_matrix_input(
            config_file=config_file,
            matrix_json=args.matrix_json,
            axis_args=args.axis_args,
        )

        # 2. Check permutation count & limits early
        variants = build_variants(resolved_matrix)

    except (UnknownSettingError, VariantLimitExceededError, DimensionLimitExceededError) as e:
        sys.stderr.write(f"Error: {e}\n")
        return 1
    except Exception as e:
        sys.stderr.write(f"Error parsing matrix input: {e}\n")
        return 1

    # 3. Initialize REST Client
    try:
        client = OrcaClient(
            base_url=args.url,
            token=args.token,
            timeout=args.timeout,
        )
    except OrcaAuthError as e:
        sys.stderr.write(f"Authentication Error: {e}\n")
        return 2
    except Exception as e:
        sys.stderr.write(f"Initialization Error: {e}\n")
        return 2

    # 4. Initialize and run MatrixRunner
    runner = MatrixRunner(
        client=client,
        output_dir=Path(args.output_dir),
        timeout=args.timeout,
        non_interactive=args.yes,
        dry_run=args.dry_run,
        auto_confirm_under_seconds=args.auto_confirm_under,
    )

    try:
        manifest_path, manifest_data = runner.run(
            resolved_matrix=resolved_matrix,
            baseline_name=args.baseline,
        )
    except OrcaConnectionError as e:
        sys.stderr.write(f"\nConnection Error: {e}\n")
        return 2
    except KeyboardInterrupt:
        sys.stderr.write("\nMatrix run cancelled by user (Ctrl+C).\n")
        return 130
    except Exception as e:
        sys.stderr.write(f"\nExecution Error: {e}\n")
        return 1

    # 5. Optional Compare Viewer Launch
    if args.launch_viewer or args.viewer_path:
        viewer_exe = find_viewer_executable(args.viewer_path)
        if viewer_exe:
            launch_compare_viewer(viewer_exe, manifest_path)
        else:
            print("\n[NOTE] Compare viewer executable not found. Specify --viewer-path to launch.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
