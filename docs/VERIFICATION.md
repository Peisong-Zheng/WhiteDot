# WhiteDot 0.3.0 product review

Tested on 23 November 2026 with English UI text, synthetic drafts and disposable settings.

## Findings and changes

| User journey | Problem found | What changed |
| --- | --- | --- |
| Start a first draft | A new user could type but had to discover the connection settings before proofreading would work. | The empty editor offers **Connect AI**. Verification requires an endpoint, model and key. An unsuccessful verification keeps the dialog open with an English explanation. Returning to the editor restores the draft and typing focus. |
| Correct a word | A short word such as “is” could match inside “This”. Clicking the last letter or using only the keyboard made a correction difficult to select. | Matching respects word boundaries and occurrences. Clicking a marked character or pressing F7 opens the suggestion. Arrow keys select, Enter applies and Esc returns to writing. **Delete** is available for a redundant word when the provider recommends removal. |
| Compare and copy | The revision could be hard to compare with the draft. Trying a second rewrite could hide a good first result when the connection failed. | The revision highlights added and changed text and keeps its own Copy button. A failed regeneration preserves the previous revision and offers **Retry rewrite**. For very long drafts the editor skips change highlighting to keep the window responsive. |
| Recover after an error | After a transient error the user had to change the draft to trigger another check. | The toolbar offers **Retry check** or **Retry rewrite**, with an explanation. Repeated clicks and continued typing during a check are covered by regression tests. |
| Return to work | Reopening a running app could appear to do nothing. Quitting could discard an uncopied draft. | Opening the executable again brings back the existing editor. Reopening a completed draft reuses the result. **Quit WhiteDot** offers to copy uncopied work or keep writing. |
| Change providers or move the app | Switching away from a custom provider could lose the saved model and endpoint. A login item could still point to the old executable after a move. | Validated provider profiles survive switching and upgrading. The login menu checks the current path. Turning the setting on again registers the new location. |

## Acceptance results

- **macOS desktop.** The real Cocoa windows were exercised on an Apple silicon Mac. The path included opening the dot, typing, verifying a rejected key and then a valid fixture key, accepting a red-underlined suggestion, rewriting with the keyboard, copying the revision, retrying after a service error, collapsing, reopening and cancelling a quit. The app's local activation socket also reopened the editor. The README screenshot was captured from this run.
- **Provider behavior.** A local HTTP fixture returned the same response format as a compatible provider and generated HTTP 401 and 503 failures on demand. Tests covered English explanations, DeepSeek's disabled thinking setting, text offsets after emoji, repeated words, preserving lines and indentation, and discarding stale responses. Clipboard payloads and the absence of a plain-text key in preferences were checked with disposable data.
- **Launcher and layout.** Pixel tests compare the halo horizontally and vertically at 1× and 2×. Other tests cover restoring the dot after its display disappears, draft and result copy availability, and singular and plural word counts. The Windows Qt platform was also exercised at 150% scale.
- **Windows desktop compatibility.** The Windows x64 Qt backend ran under Wine on macOS. The fixture exercised editor focus, suggestion selection, rewriting, collapsing and reopening. It also wrote, read and removed a synthetic Windows credential and login entry in an isolated Wine profile. Physical Windows display changes, Explorer's notification area and the next real Windows sign-in still need a Windows machine.
- **Service coverage.** This review used a deterministic local provider. Live provider uptime, account permissions, billing and model output quality depend on the account and model in use. The optional live DeepSeek probe is documented in the README.

## Packaged applications

| Package | Checks on the final artifact |
| --- | --- |
| Apple silicon macOS ZIP | Extracted the app, verified its strict ad-hoc signature and 0.3.0 bundle version, and ran its offline self-test with both the Cocoa and minimal Qt backends. The bundled Qt Python bindings require macOS 15 or later. |
| Portable Windows x64 EXE | Checked its x64 GUI format and embedded 0.3.0 file and product versions. Ran its packaged self-test with both the Windows GUI and minimal Qt backends under Wine. Two Windows processes also exercised activation of the existing editor. |

All 41 regression tests passed on macOS and under Windows CPython in Wine. A separate scan found no remaining Han text in the project's own source, tests or documentation.

From the repository root, run `python -m unittest discover -s tests -v` for the 41 regression tests. The executable on each platform accepts `--self-test` for an offline packaging check. The [Windows guide](WINDOWS.md) includes the hands-on Windows checklist.
