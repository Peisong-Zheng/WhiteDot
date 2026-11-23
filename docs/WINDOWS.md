# Windows 实机调试与发布

## 使用便携版

在仓库的 **Releases** 页面下载 `WhiteDot-windows-x64.exe`，保存到一个长期保留的目录，双击即可运行。右侧偏下会出现白点，系统托盘的折叠菜单中可以找到 WhiteDot。右键托盘图标可设置模型服务和登录启动。更改 EXE 存放位置后，重新切换一次登录启动开关，让注册表记录新路径。

首次使用在设置中选择提供商、填写模型和自己的 API Key，再进行验证。验证会向选定的 API 端点发起一次小请求。Windows 凭据管理器保存密钥，`%APPDATA%\WhiteDot\settings.json` 保存普通设置。进行屏幕共享或向 AI 描述故障时，只提供错误类型、应用版本及合成样例。

Windows 包由 PyInstaller 单文件模式生成，双击后会先把 Qt 和 Python 运行时展开到临时目录。首次启动可能慢几秒。当前工作流生成未进行 Authenticode 签名的 EXE，企业设备的应用控制策略可能会阻止运行。可用 PowerShell 的 `Get-FileHash .\WhiteDot-windows-x64.exe` 核对 Release 的 `SHA256SUMS.txt`。

### Chrome 与 Edge 的可选扩展

当浏览器输入框无法显示准确的红线时，可从同一个 Release 下载 `WhiteDot-browser-extension.zip` 并解压到长期保留的文件夹。在 `chrome://extensions` 或 `edge://extensions` 打开开发者模式，点击“加载已解压的扩展”，选择直接含有 `manifest.json` 的文件夹。通过 WhiteDot 托盘菜单启用浏览器连接，然后将配对码填入扩展弹窗。配对码只供桌面程序和本机扩展连接；模型 API Key 始终在桌面设置中填写。扩展依赖正在运行的 WhiteDot。

## 用 VS Code 打开源码

1. 通过 VS Code 的 **Git: Clone** 克隆公开仓库。打开包含 `main.py`、`WhiteDot.spec` 和 `.github` 的目录。
2. 安装 Windows x64 的 Python 3.11。以下命令可直接交给 VS Code 中的 AI 代理执行，使用虚拟环境的解释器路径可以避免 PowerShell 脚本执行策略限制。
3. 普通使用和调试采用同一 Windows 用户登录会话，目标编辑器和 WhiteDot 均以普通用户权限启动。

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py --self-test
.\.venv\Scripts\python.exe main.py
```

在 Windows 本机构建与 Release 相同的文件：

```powershell
.\.venv\Scripts\python.exe scripts\build.py
```

脚本生成 UI Automation 类型库绑定，运行 PyInstaller，并对打包后的程序执行离线自检。x64 成品路径为 `dist\WhiteDot-windows-x64.exe`。可在没有 Python 开发环境的普通 Windows 用户账号中双击验收。重复打包前，请从托盘退出正在运行的同路径 EXE。

## 实机验收

先在 Chrome 或 Edge 打开仓库里的 `tests/fixtures/browser-fields.html`。页面只包含合成样例，也可作为离线本地文件打开。AI 检查仍需连接已配置的模型。用相同样例检查 Codex 的消息输入框，记录 Windows、浏览器及 Codex 的版本和显示缩放。

| 操作 | 应观察到的行为 |
| --- | --- |
| 在单行框末尾输入空格后停顿 | 有模型配置时，`speling` 应产生建议。宿主提供词坐标时，红线出现在该词下方。 |
| 在多行框里接受第二个 `teh` 的建议 | 第一个拼错的词保持原样。第二行前的 emoji 不应导致错位。 |
| 让旧建议保持可见，然后继续输入或切换到另一个文本框 | 过期建议不能覆盖刚输入的内容或其他输入框。 |
| 将焦点放在 Codex 消息输入框，输入 `She go home.`，点击白点 | 当该版本公开可编辑文本时，能看到基于当前内容的语法重写；检查实际显示的来源与原文。 |
| 在带粗体的富文本框中尝试建议 | 确认原有粗体和结构得到保留。宿主缺少安全定点写入能力时，请使用面板复制。 |
| 聚焦密码框、只读输入框、空白处 | 这些控件不应被自动校对。此时从白点打开手动输入框。 |
| 手动输入、接受建议、重写全文、复制 | 空输入时复制禁用。重写后上下对照，并可单独复制下方结果。 |
| 在缩放为 100% 与 150% 的两台显示器间移动浏览器 | 白点可拖动，拼写线跟随目标词和当前显示器缩放。滚动后检查有无残留。 |
| 移动白点、开关登录启动、重新登录 | 开关状态和白点位置应保留。关闭后下次登录不会自行启动。 |
| 输入错误 API Key并保存 | 设置应提示验证失败。已验证的配置应继续可用。 |

## 无法捕捉某个应用时

Windows 适配器读取前台控件的 UI Automation 信息。使用 Accessibility Insights for Windows 的 **Live Inspect** 选中**合成文本**输入框，观察 `ControlType`、`HasKeyboardFocus`、`IsPassword`、是否具有可写 `ValuePattern`、`TextPattern` 以及词范围边界。记录可用模式即可；故障报告不需要真实的输入内容。[Microsoft 的 UIA 文本模式说明](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-implementingtextandtextrange)

- 只能看到浏览器的只读 `Document` 时，先点入实际文本框。部分 Electron、自绘编辑器或特定版本可能只暴露外层窗口。此时白点可打开手动编辑器。
- 有 `ValuePattern` 可读而缺少 `TextPattern` 时，程序能读取内容并显示重写，但无法取得可信的词级坐标。文本跨行、emoji、重复拼写等情况会再次核对词前内容。
- 可写的纯文本 Edit 控件支持接受建议。富文本的子控件可能代表格式或嵌入对象。当前适配器会拒绝有丢失结构风险的整框写入，仍可从面板复制。
- 权限级别、远程桌面的当前会话及系统安全桌面会影响 UI Automation。用普通用户权限启动两个程序，在同一会话中测试。
- 首次从源码运行时，`comtypes` 会从 Windows 自带的 `UIAutomationCore.dll` 生成绑定。便携包在构建时生成并收集这些绑定。

平台接口位于 `whitedot/platforms/windows.py`。`capture()` 返回焦点快照，`rects()` 返回可见的词级矩形，`replace()` 在修改前复核控件标识与原文。跨平台偏移以 Python Unicode 码点为单位，Windows 适配器负责处理提供程序的字符单位、换行符和屏幕缩放。更改前先运行 `tests/test_windows_adapter.py`，并用上述场景覆盖真实的浏览器与 Codex。

可复制给 Windows 端代理：

> 请在当前 WhiteDot 项目按 docs/WINDOWS.md 建立虚拟环境、运行离线测试并打包便携 EXE。优先验证 Chrome/Edge 和 Codex 输入框的捕捉、重复错词的位置、点击建议和输入过程中切换焦点的行为。使用 tests/fixtures/browser-fields.html 和合成段落；由我在程序设置里输入密钥。记录实际可复现的问题、程序版本和缩放比例。将 Windows 平台修正放在 whitedot/platforms/windows.py，共享逻辑单独测试，然后重新构建同一套 Release 产物。

## GitHub Release

源码可在 Mac 和 Windows 共用。每个二进制包由对应操作系统的 runner 生成。PyInstaller 官方说明需要在目标操作系统上构建相应的分发包。[PyInstaller 官方文档](https://pyinstaller.org/en/stable/)

1. 仓库根目录须直接包含 `.github/workflows/release.yml`。在 VS Code 首次发布仓库时选择 Public，并让 GitHub Actions 在仓库中启用。
2. 在 GitHub 网页选择 **Actions → Build desktop releases → Run workflow**，选择已推送的主分支。如果只想试构建，将 **Optional release tag** 留空。运行成功后可在该次运行的 **Artifacts** 下载两个包。
3. 要发布公开下载，在同一窗口的 **Optional release tag** 填写版本号，例如 `v0.1.0`，然后点击 **Run workflow**。两个平台的自动测试、打包和成品自检全部成功后，工作流会为本次构建的提交创建标签和 Release，上传 Windows EXE、macOS ZIP、可选浏览器扩展 ZIP 和 SHA-256 校验表。
4. 同一提交可以用原标签重跑，同名下载文件会被替换。如果原标签已指向另一个提交，工作流会保留已有版本并提示改用新版本号。已通过 VS Code 推送的版本标签也会触发发布。仓库或组织必须允许该工作流的 `contents: write` 权限。
