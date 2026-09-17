# OrcaSlicer Matrix Studio v2.0.2 — Windows x64

This patch release fixes local Remote API token discovery and persistence in Matrix Studio.

## What was wrong

- Matrix Studio's connection client could discover OrcaSlicer's token internally, but the Settings page intentionally returned an empty token for local endpoints such as `127.0.0.1`.
- The Save action intentionally skipped secure credential storage for those same local endpoints.
- As a result, the masked API-token field did not auto-populate and a manually entered token disappeared after Matrix Studio was reopened.

## What changed

- Local connections now read OrcaSlicer's current `remote_api_token` during Studio startup and populate the masked Settings field.
- OrcaSlicer's live configuration value takes priority so token rotation is picked up on the next Studio launch.
- If local configuration discovery is unavailable, Matrix Studio falls back to the securely stored credential.
- Saving now stores local and remote API tokens consistently in Windows Credential Manager.
- Settings are explicitly synchronized to disk when **Save settings** is pressed.
- Added regression tests covering local auto-discovery and a complete save/close/relaunch cycle.

## Verification

- 108 tests passed and one optional test was skipped.
- Token discovery was verified against the current OrcaSlicer configuration without exposing the secret.
- Windows Credential Manager's `WinVaultKeyring` backend was detected and used for secure persistence.
- Both frozen Windows executables passed the packaged Qt runtime smoke test.
- OrcaSlicer's exact Matrix Studio `--connect http://127.0.0.1:13130` launch path was tested.

## Which file should I download?

### `OrcaSlicer-MatrixStudio-v2.0.2-Windows-x64.zip` — recommended

The complete portable OrcaSlicer and Matrix Studio suite.

### `OrcaMatrixStudio-v2.0.2-Windows-x64.zip` — standalone companion

Matrix Studio without OrcaSlicer. It still requires the compatible custom OrcaSlicer build for slicing.
