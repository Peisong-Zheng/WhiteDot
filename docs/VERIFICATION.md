# Folio 0.5.0 verification

Tested on 23 November 2026 with synthetic drafts, a temporary local connection file and a loopback HTTP provider.

## Time to underline

On an Apple silicon Mac, the Cocoa editor received real Qt keyboard events. The timer started at the keypress or paste and stopped when the event loop had processed the red underline on the target word. These are editor timings. Display refresh and a commercial provider's response time are separate.

| Interaction | Result on the test Mac |
| --- | --- |
| Paste `I can recieve mail.` into a newly focused editor, with the spelling dictionary still cold | 28 ms |
| Press Space after `teh`, across 30 trials | 1.4 ms median, 4.1 ms maximum |
| Stop typing at the end of `seperate`, without adding a space | 169 ms, including the 160 ms word-completion delay |
| Type a second typo during a deliberately blocked AI request | Both spelling marks were available for selection before the provider was allowed to return. |

A separate head-to-head test loaded the 0.4.0 and 0.5.0 editors with the same provider fixture, which always took 1.5 seconds to answer. With the minimal Qt backend, pressing Space after `I saw teh` produced the underline in **2,413 ms on 0.4.0** and **1.3 ms on 0.5.0**.

With the HTTP service paused, the editor accepted further typing. After the service returned, the grammar suggestion for an unchanged sentence appeared alongside the local spelling suggestions. Editing that sentence removed the outdated suggestion. F7 and Enter applied a local correction before an AI provider was configured. Tests also cover pasted text, Unicode offsets, regional spellings, code, word repetition and common subject–verb errors.

## Upgrade and credentials

A simulated Folio 0.4 profile retained its provider and prompted for a one-time key re-entry. Local corrections worked throughout. An HTTP 401 left the connection unsaved. A successful validation created the local connections file with mode 0600 on macOS. A fresh instance then used the saved key for grammar and rewriting without requiring another setup. Opening settings showed only the saved status.

The same interaction test blocked imports of the old system credential backend throughout. No import was attempted. Further tests cover interrupted writes, malformed connection files, key rotation and isolation between endpoints.

## Release packages

The Apple silicon ZIP and the Windows x64 EXE both identify themselves as Folio 0.5.0. The extracted macOS app passed strict, deep signature verification. Both packaged applications passed `--self-test` with their GUI and minimal Qt backends. Their bundled archives contain the offline dictionary and omit the old keyring library.

All 59 regression tests passed on macOS. Windows CPython under Wine passed 58 and skipped the POSIX file-permission test. Typing and applying a local correction were also verified in the Windows Qt GUI at 150% scale. Physical Windows hardware and paid model response times were outside this run.

## Reproduce

Run `python -m unittest discover -s tests -v` from the repository root. Each release executable accepts `--self-test` to check offline spelling, an old-profile upgrade, a local credential round trip, correction selection and draft retention against temporary files. The [Windows guide](WINDOWS.md) includes the native acceptance checklist.
