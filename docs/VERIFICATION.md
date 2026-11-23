# Folio 0.4.0 product review

Reviewed on 23 November 2026. This release renames WhiteDot to Folio, simplifies the floating editor and changes when the application accesses saved credentials.

## Credential and editor checks

| Scenario | Observed behavior |
| --- | --- |
| Open with a saved profile | A cold launch and opening the empty editor used only the local endpoint and account metadata. |
| Browse settings | With native macOS windows, three cycles of opening settings, switching providers, choosing **Change key**, cancelling and returning to the editor produced zero reads, writes or deletes on the instrumented credential store. The saved view displayed **Saved**, and the replacement field opened empty. |
| Reject a replacement | The local provider rejected a test key with HTTP 401. The saved profile still worked. Cancelling the dialog retained the original settings. |
| Check and rewrite | The first actual proofreading request used the saved key once. Subsequent checks, several rewrites, HTTP 503 recovery and reopening the editor reused it. The coverage included a pre-0.4 account entry. |
| Access denied or delayed | The controller stops automatic credential retries after a denial. **Retry access** enables a deliberate retry. A draft edited or collapsed while authorization is pending is discarded before submission. |
| Upgrade the launcher | Login-item tests cover an enabled Windows or macOS registration in the same folder and a launch from a different folder. An in-place upgrade transfers the old login entry to the new executable. |
| Work in the compact editor | The empty draft, correction, retry and stacked draft and revision were checked with native Cocoa controls. Click and keyboard suggestion selection, Escape, copying and returning to the draft passed. The README screenshot is from the running editor. |

The macOS interaction checks used an instrumented credential store and a loopback HTTP provider with disposable test data. A system authorization dialog for a particular user's existing key depends on that Mac's Keychain settings and its trust in the updated application. No personal credential or paid provider account was used.

## Packaged applications

- **macOS.** The Apple silicon ZIP was extracted and its Folio 0.4.0 bundle passed deep, strict signature verification. The packaged saved-profile self-test passed with both the native Cocoa and minimal Qt backends. Use the ZIP for distribution. Finder can attach metadata to a loose bundle inside a synced project folder.
- **Windows.** The x64 portable executable passed its packaged self-test with the Windows GUI and minimal Qt backends in an isolated Wine environment. At 150% scaling, opening the saved settings and cancelling a key change produced zero credential reads. A separate test used a disposable Windows Credential Manager entry to check key rotation and a temporary user registry entry to check login migration. Physical Windows sign-in and multiple displays were outside this run.

## Repeat the checks

All 48 automated tests passed on macOS and under Windows CPython in Wine. Run `python -m unittest discover -s tests -v` from the repository root. Run `--self-test` on the release executable to exercise a saved profile, its empty replacement field, cancelling settings, applying a correction and reopening the editor. It uses temporary preferences and performs zero credential reads. The [Windows guide](WINDOWS.md) includes the hands-on platform checks.
