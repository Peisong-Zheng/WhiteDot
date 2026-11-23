# Folio

Folio is a floating English proofreading editor for macOS and Windows. Click the white dot, type or paste a draft, and pause to check its spelling and grammar. Click an underlined word to choose a correction. You can also rewrite the whole draft and copy the result.

![Folio showing a draft, an inline correction and the rewritten text](docs/editor.png)

## Install and open

| Platform | Download | Start the app |
| --- | --- | --- |
| Apple silicon, macOS 15 or later | `Folio-macos-arm64.zip` | Unzip the download, move `Folio.app` to Applications and open it. The build is ad-hoc signed. Intel Mac users can build from source on their own Mac. |
| Windows 10 or 11, x64 | `Folio-windows-x64.exe` | Save the portable executable in a permanent folder and double-click it. Look for the dot near the lower-right corner of the screen and the tray icon in the notification area. |

The Windows portable executable is also included in this checkout. [Windows EXE](dist/Folio-windows-x64.exe) · [GitHub releases](https://github.com/Peisong-Zheng/WhiteDot/releases)

**Upgrading from WhiteDot:** copy your draft, quit WhiteDot from its menu, and open Folio. Folio reuses your existing provider, saved credential and dot position. If you enabled login startup, place the new app alongside the old one so Folio can update the login item. If you choose another location, enable **Open at login** there. If you previously installed the optional 0.1 browser extension, you can remove it in your browser's extension settings.

## Check your first draft

1. Click the floating dot and choose **Connect AI** for first-time setup. To change the provider or replace a saved key later, right-click the dot or use the menu bar or tray icon and choose **AI settings**.
2. Choose a provider and model, enter your API key, and choose **Verify and save**. Folio checks the connection using a fixed English sample before saving the configuration.
3. Try `I saw teh cat.` After a brief pause, Folio checks the draft. Click the red underline and choose `the`.
4. Select **Rewrite** to correct the entire draft. The revision opens below the draft, with new or changed words highlighted. Each section has its own **Copy** button.

| Action | How |
| --- | --- |
| Open or collapse | Click the dot. Press Esc inside the editor to collapse it. |
| Review suggestions | Press F7, use Up or Down to choose a replacement, and press Enter to apply it. Esc returns to the draft. |
| Rewrite | Press Command+Return on macOS or Ctrl+Enter on Windows. |
| Move the dot | Drag it to a new position. It remembers that position after you quit. |
| Start at login | Right-click the dot or tray icon and toggle the login setting. If you move the executable later, toggle the setting again to update its path. |
| Resume writing | Click the dot again. Your draft and completed rewrite stay in memory until you quit. |

## Providers and privacy

Folio sends the English draft you enter in **its own editor** to your selected provider for proofreading. A mixed-language draft is submitted in full. The limit is 24,000 characters per request. Closing the editor cancels checks still waiting to start. If you edit while a request is in flight, Folio discards the old response. Provider fees apply. Folio offers to copy an unsaved draft or revision when you quit.

DeepSeek requests explicitly disable thinking for connection tests, proofreading and rewriting. OpenAI and Gemini have presets, and compatible Chat Completions endpoints can use the custom setting. The selected model must return the requested JSON structure. Rewrites aim to preserve meaning and tone, and Folio verifies the line structure before displaying the result. [DeepSeek thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/)

Saved keys stay in macOS Keychain or Windows Credential Manager. Opening the editor or browsing AI settings uses public preferences. A saved key is never filled into a text field. Choose **Change key** in AI settings to enter a replacement. Folio validates a replacement before saving it.

When Folio first needs an existing key for proofreading or rewriting, macOS may ask you to authorize the updated app. After a successful read, Folio reuses the key for that session. [Apple's guide to keychain access after an app update](https://support.apple.com/guide/keychain-access/if-a-trusted-app-asks-for-keychain-access-kyca1331/mac)

Preferences keep their original location for upgrades. They live in `~/Library/Application Support/WhiteDot/settings.json` on macOS and `%APPDATA%\WhiteDot\settings.json` on Windows.

## Run from source

Use Python 3.11 or later. On macOS, open the folder containing `main.py` and run:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-build.txt
python main.py
```

To test and package the app on the current platform:

```sh
QT_QPA_PLATFORM=minimal python -m unittest discover -s tests -v
QT_QPA_PLATFORM=minimal python main.py --self-test
python scripts/build.py
```

The packaged self-test runs locally without a provider account. For an optional live DeepSeek check, run `python scripts/probe_deepseek.py` and enter your key at the hidden prompt. Windows setup, PowerShell commands and an acceptance checklist are in the [Windows guide](docs/WINDOWS.md).

## Maintain and release

The shared editor and launcher are in `whitedot/windows_ui.py`. The controller in `whitedot/app.py` owns draft revisions, provider requests and menus. Provider protocols and credential storage are in `whitedot/provider.py` and `whitedot/settings.py`. The Spectral typeface ships with the app. [Font source](https://github.com/google/fonts/tree/main/ofl/spectral) · [Font license](whitedot/assets/OFL.txt)

After syncing the source in VS Code, open **Actions → Build desktop releases → Run workflow** on GitHub. Leave the release tag blank to try the build. To publish, use a new tag such as `v0.4.0`. The workflow builds on separate macOS and Windows runners and uploads both desktop binaries with SHA-256 checksums after the builds pass. [Verification record](docs/VERIFICATION.md)
