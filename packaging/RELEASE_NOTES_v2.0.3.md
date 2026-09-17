# OrcaSlicer Matrix Studio v2.0.3 — Windows x64

This release fixes the remaining local API-token handoff problem. Matrix Studio can now be launched repeatedly from OrcaSlicer without copying and pasting the API key each time.

## What changed

- OrcaSlicer now passes its current in-memory `remote_api_token` to Matrix Studio through the child-process environment.
- The token is not placed on the command line, so it is not exposed in the process command-line listing.
- Matrix Studio now uses token sources in this order:
  1. the live token supplied by the OrcaSlicer parent process;
  2. the credential saved in Windows Credential Manager;
  3. OrcaSlicer's on-disk configuration as a standalone-launch fallback.
- A stale `OrcaSlicer.conf` value can no longer overwrite a known-good saved credential on every launch.
- Added regression coverage for live-token handoff, saved-credential precedence, configuration fallback, and relaunch persistence.

## Why v2.0.2 could still fail

OrcaSlicer had generated or rotated a live API token but had not necessarily flushed that value to `OrcaSlicer.conf`. Version 2.0.2 preferred the configuration file over Windows Credential Manager, so it replaced the valid saved token with the stale file value and OrcaSlicer rejected the connection. Version 2.0.3 removes that race and reverses the unsafe fallback order.

## Downloads

### `OrcaSlicer-MatrixStudio-v2.0.3-Windows-x64.zip` — recommended

The complete portable OrcaSlicer build with Matrix Studio included. Extract the entire archive to a new folder and launch `orca-slicer.exe`; do not copy it over an older extraction.

### `OrcaMatrixStudio-v2.0.3-Windows-x64.zip` — standalone companion

Matrix Studio only. Use this when you already have the matching integrated OrcaSlicer build.

## Source

- Matrix Studio v2.0.3: https://github.com/schwaaaat/orcaslicer-matrix-tool/tree/v2.0.3
- Integrated OrcaSlicer source: https://github.com/schwaaaat/OrcaSlicer/tree/matrix-studio-v2.0.3
