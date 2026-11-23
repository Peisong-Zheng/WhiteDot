# WhiteDot on Windows

## Start the portable app

Download `WhiteDot-windows-x64.exe` from the release for your version. Store it in a permanent folder and double-click it. The first launch can take a few seconds while Windows loads the bundled Python and Qt runtime. The movable white dot appears on screen. The tray icon may be under the notification area's up arrow. [Windows EXE in this checkout](../dist/WhiteDot-windows-x64.exe) · [WhiteDot releases](https://github.com/Peisong-Zheng/WhiteDot/releases)

When upgrading, copy any draft you want to keep and quit the running app from the tray. Then replace the old EXE in the same folder. WhiteDot reuses the current user's key, provider settings and launcher position. If you move the EXE after enabling login startup, toggle the login setting again to register the new path. If the 0.1 browser extension is still installed, you may remove it in the browser's extension manager.

Click the dot and choose **Connect AI**. Enter your key in **AI settings** and choose **Verify and save** to test the selected model with a fixed sample. After that, type or paste a draft in WhiteDot. Pause to see corrections, click a red underline to apply a suggestion, or choose **Rewrite** and review the result below the draft. Copy either section and paste it into the destination app yourself. WhiteDot keeps the current draft in memory while the panel is collapsed.

Credentials are stored in Windows Credential Manager. Ordinary preferences are in `%APPDATA%\WhiteDot\settings.json`. The portable executable is unsigned. To verify a downloaded release against the published `SHA256SUMS.txt`, use:

```powershell
Get-FileHash .\WhiteDot-windows-x64.exe -Algorithm SHA256
```

## Develop and build

Install 64-bit Python 3.11 and open the project folder containing `main.py` and `WhiteDot.spec` in VS Code. These PowerShell commands work without activating the virtual environment:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py --self-test
.\.venv\Scripts\python.exe main.py
```

Quit a running copy from `dist` before rebuilding it. The build script generates the single-file EXE and checks that it can launch and exercise the editor offline:

```powershell
.\.venv\Scripts\python.exe scripts\build.py
```

Find the output at `dist\WhiteDot-windows-x64.exe`. You can use **Properties → Details** to check the file and product versions.

## Acceptance checks

| Scenario | What to verify |
| --- | --- |
| First launch | Open the dot. Confirm the editor accepts input right away and gives a clear route to setting up your provider. |
| Suggestions | Type `I saw teh cat.` and choose `the` from the highlighted word. Repeat using F7 and Enter. Also try a repeated typo and a typo after an emoji. |
| Revisions | Edit before a check or rewrite finishes. The old result must never replace a newer draft. |
| Draft and result | Rewrite with Ctrl+Enter. Copy each section into a scratch document and compare it with the text you saw. Collapse and reopen the editor to resume your draft. |
| Launcher and scaling | View the dot against light and dark backgrounds. Move it between 100% and 150% displays and near each edge. Check that the editor, controls and suggestion list stay visible. |
| Settings and recovery | Try an invalid key, check the English error, then cancel. Confirm the previous validated configuration still works. Toggle login startup and test the next sign-in. |

For a Windows coding agent:

> Start WhiteDot from source, run the offline tests and package the x64 EXE. Verify the scenarios above using synthetic drafts. I will enter my provider key in the app. Record the Windows version, display scaling and repeatable steps for any failure. After changes, run the same suite and the packaged smoke test again.

## Publish both downloads

1. Sync the source to your GitHub repository from VS Code.
2. Open **Actions → Build desktop releases → Run workflow** and choose the synced branch. Leave the release tag empty for downloadable test artifacts.
3. To publish, specify an unused version tag such as `v0.3.0`. The workflow publishes the macOS ZIP, portable Windows EXE and SHA-256 checksums together after both builds pass. Pushing a version tag also triggers the workflow.
