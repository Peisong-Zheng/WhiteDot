# Folio

Folio is a floating English proofreading editor for macOS and Windows. Click the white dot and start typing. Common spelling mistakes are underlined locally as you finish each word, even offline. Connect an AI provider for sentence-level proofreading and rewrites. Click an underlined word to choose a correction. You can also rewrite the whole draft and copy the result.

![Folio showing a draft, an inline correction and the rewritten text](docs/editor.png)

## Install and open

| Platform | Download | Start the app |
| --- | --- | --- |
| Apple silicon, macOS 15 or later | `Folio-macos-arm64.zip` | Unzip the download, move `Folio.app` to Applications and open it. The build is ad-hoc signed. Intel Mac users can build from source on their own Mac. |
| Windows 10 or 11, x64 | `Folio-windows-x64.exe` | Save the portable executable in a permanent folder and double-click it. Look for the dot near the lower-right corner of the screen and the tray icon in the notification area. |

The Windows portable executable is also included in this checkout. [Windows EXE](dist/Folio-windows-x64.exe) · [GitHub releases](https://github.com/Peisong-Zheng/WhiteDot/releases)

**Upgrading from Folio 0.4 or WhiteDot?** Copy your draft, quit the old app from its menu and open the new version. Your provider, model and dot position carry over. Open **AI settings** from the dot or tray menu and re-enter the API key once for each provider you use. Folio leaves existing Keychain and Credential Manager entries untouched.

If you enabled login startup in WhiteDot, install Folio in the same folder so it can update the login item. If you choose another location, enable **Open at login** there.

## Check your first draft

1. Click the floating dot. Type `I saw teh cat.` The local checker underlines `teh` as you reach the following space. Click it and choose `the`. This works before you connect a provider.
2. To enable sentence checks and rewrites, open **AI settings** from the dot's right-click menu or from the menu bar or tray icon. Enter a provider, model and key, then choose **Verify and save**. Folio uses a fixed English sample for validation.
3. Keep writing while the AI checks the draft. Click a marked word or press F7 to see suggestions.
4. Select **Rewrite** to see the revised draft below the original, with new or changed words highlighted. Each section has its own **Copy** button.

| Action | How |
| --- | --- |
| Open or collapse | Click the dot. Press Esc inside the editor to collapse it. |
| Review suggestions | Press F7, use Up or Down to choose a replacement, and press Enter to apply it. Esc returns to the draft. |
| Rewrite | Press Command+Return on macOS or Ctrl+Enter on Windows. |
| Move the dot | Drag it to a new position. It remembers that position after you quit. |
| Start at login | Right-click the dot or tray icon and toggle the login setting. If you move the executable later, toggle the setting again to update its path. |
| Resume writing | Click the dot again. Your draft and completed rewrite stay in memory until you quit. |

## Providers and privacy

Local spelling runs on your device. Once you configure a provider, Folio also sends the draft in its own editor to that provider for proofreading. Mixed-language drafts are submitted in full. The limit is 24,000 characters per request. After further edits, Folio keeps applicable suggestions for unchanged sentences and discards outdated ones. Provider fees apply. Closing the editor cancels a check still waiting to start.

DeepSeek requests explicitly disable thinking for connection tests, proofreading and rewriting. OpenAI and Gemini have presets, and compatible Chat Completions endpoints can use the custom setting. The selected model must return the requested JSON structure. Rewrites aim to preserve meaning and tone, and Folio verifies the line structure before displaying the result. [DeepSeek thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/)

Validated keys are saved in **plain text** in your local user profile. Folio uses this file for connections, including after a restart. Anyone who can read the file can use its keys. The settings dialog displays the saved status and offers **Change key**. It never displays a stored key.

| Platform | Connection file | Dot position and earlier preferences |
| --- | --- | --- |
| macOS | `~/Library/Application Support/WhiteDot/connections.json` (owner read/write, mode 0600) | `~/Library/Application Support/WhiteDot/settings.json` |
| Windows | `%LOCALAPPDATA%\Folio\connections.json` (inherits local user profile permissions) | `%APPDATA%\WhiteDot\settings.json` |

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

The shared editor and launcher are in `whitedot/windows_ui.py`. The controller in `whitedot/app.py` owns draft revisions, provider requests and menus. Provider protocols and credential storage are in `whitedot/provider.py` and `whitedot/settings.py`. The offline checker uses the bundled typos project dictionary. [Spelling data and license](whitedot/assets/TYPOS-LICENSE.txt)

The Spectral typeface ships with the app. [Font source](https://github.com/google/fonts/tree/main/ofl/spectral) · [Font license](whitedot/assets/OFL.txt)

After syncing the source in VS Code, open **Actions → Build desktop releases → Run workflow** on GitHub. Leave the release tag blank to try the build. To publish, use a new tag such as `v0.5.0`. The workflow builds on separate macOS and Windows runners and uploads both desktop binaries with SHA-256 checksums after the builds pass. [Verification record](docs/VERIFICATION.md)
