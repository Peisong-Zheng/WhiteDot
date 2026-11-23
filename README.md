# WhiteDot 白点英文校对

WhiteDot 是一个运行在 macOS 和 Windows 上的英文拼写与语法检查器。输入时它停在屏幕边缘。支持的文本框里会出现红色波浪线，点击**红线**可以查看解释、选择替换词。点击**白点**可以查看整段语法重写。原应用没有暴露可编辑文本时，白点会打开一个临时编辑器。

## 首次使用

1. **macOS**：解压 `WhiteDot-macos-arm64.zip`，把 `WhiteDot.app` 移到「应用程序」并打开。本地提供的包适用于 Apple 芯片，使用 ad-hoc 签名，尚未进行 Apple 公证。从网页下载后若 macOS 提示无法验证开发者，可按系统的「隐私与安全性」界面核对来源并选择打开。Intel Mac 可从源码运行，或在 Intel Mac 上生成 x64 包。
2. **Windows x64**：从 Release 下载 `WhiteDot-windows-x64.exe`，放在固定位置并双击。它是免安装单文件程序。桌面图标位于任务栏通知区域，可能折叠在向上箭头中。
3. 右键白点或菜单栏／托盘图标，选择 **AI 服务与密钥…**。选服务商，核对地址和模型，输入自己的 Key，点 **验证并保存**。程序会用固定英文例句验证模型是否能执行校对。错误会在设置窗口显示，原有配置可继续使用。
4. Mac 用户在同一菜单选择 **授予辅助功能权限…**，在「系统设置 → 隐私与安全性 → 辅助功能」中开启 WhiteDot，然后回到原输入框。开发版与打包版可能需要分别授权。Windows 普通桌面应用通常不需要管理员权限。
5. 在浏览器或其他应用的英文输入框输入 `She go to teh library every day.`，停顿约 0.9 秒并等候服务响应。点击红线选择建议。再点白点，上方可核对原文，下方是整段改写。点击 **复制** 取用结果。

右键菜单里的 **自动检查当前输入框** 可以随时暂停或恢复外部校对。暂停时点白点即可使用手动编辑器。**登录时启动** 默认关闭，开启后会在当前系统用户下次登录时启动。移动程序后请重新切换一次此开关。白点默认在主屏幕右侧偏下，拖动即可保存位置。外接显示器移除后，白点会回到可见屏幕。

## Chrome 和 Edge 的网页红线

浏览器原生辅助功能可以处理很多普通输入框。富文本、换行排版或缩放后遇到红线缺失时，安装配套扩展可以让浏览器直接定位错词，并在网页内采纳建议。它和桌面白点共用同一个模型配置。

1. 将 Release 中的 `WhiteDot-browser-extension.zip` 解压到一个保留的文件夹。开发时可直接选项目的 `browser-extension` 目录。
2. 在 Chrome 的 `chrome://extensions` 或 Edge 的 `edge://extensions` 页面开启「开发者模式」，点击「加载已解压的扩展程序」，选择**直接包含 manifest.json** 的文件夹。
3. 在桌面白点右键菜单选择 **浏览器扩展连接… → 启用连接 → 复制配对码**。点浏览器工具栏里的 WhiteDot 图标，把配对码粘贴到扩展并保存。刷新已打开的网页。
4. 点入 HTTP 或 HTTPS 网页里的输入框。扩展负责在网页内画线和采纳替换；点桌面白点仍可打开整段重写。桌面程序须保持运行。浏览器内置页面、地址栏和无法读出光标的自绘编辑器可以使用系统接入或临时编辑器。

配对码只用于这台电脑，扩展经本机回环接口与桌面端交换当前输入框和建议。模型请求由桌面端发出。停用连接会使旧配对码失效。测试页如需验证扩展，可在项目根目录执行 `python -m http.server 8000 --bind 127.0.0.1 --directory tests/fixtures`，然后访问 `http://127.0.0.1:8000/browser-fields.html`。

## 白点打开什么

| 光标或窗口状态 | 点开后的行为 |
| --- | --- |
| 前台应用提供可读取的可编辑文本 | 显示原文，自动请求整框语法重写。原文用红线列出已定位的建议。重写结果可复制，用户决定是否粘回。 |
| 应用可读但缺少词级屏幕坐标 | 原文面板仍支持点击红线查看建议和复制重写。 |
| 原应用不能安全地接受某条替换 | 在面板显示采用该项建议的修正版，供核对和复制。 |
| 前台没有可读取的输入框、外部检查已暂停，或没有辅助功能权限 | 打开临时编辑器。可直接输入、粘贴、校对和复制。点 **语法重写** 才会展开下半区，原文和结果各有复制按钮。 |
| 再点白点、点 ×，或在临时编辑器按 Esc | 收起面板。手动草稿仅在当前进程内保留，退出即清除。 |

空文本的复制按钮会禁用。修改输入后，旧红线和重写结果会失效。后台返回旧结果或用户已经切换了输入框时，程序会丢弃旧建议。语法重写要求保留含义、语气、数字和引用，程序还会校验行数并保留空行、换行符和缩进。模型输出仍需由使用者核对。

## 模型、数据与费用

- **DeepSeek** 使用官方 Chat Completions，所有请求显式发送 `thinking.type = disabled`，包括密钥验证、逐项校对和整段重写。模型名称可以在设置中修改。[DeepSeek 推理模式](https://api-docs.deepseek.com/guides/thinking_mode/)
- **OpenAI、Gemini** 提供预设。其他实现 OpenAI Chat Completions 的服务可选择 **Custom**，填写 HTTPS 基础地址和模型，例如使用自己的兼容网关。本机回环地址支持 HTTP。服务需要返回符合提示格式的 JSON。自定义服务的推理参数由该服务配置。
- 已设置密钥并开启自动检查时，当前可编辑输入框的**整段内容**会发送到所选模型服务，按服务商计费。中英混排也会发送整段。只需手动校对时，可在托盘关闭自动检查。输入持续变化时会等待停顿再发送。每次最多 24,000 个 Unicode 字符，超长时会提示分段。
- 系统密码框、只读控件与明显带常见密钥格式的文本会跳过校对。普通输入框可能包含敏感正文，是否发送由当前的监控开关决定。程序不记录输入历史。密钥保存在 macOS 钥匙串或 Windows 凭据管理器中，普通 JSON 设置只保存模型、端点和界面偏好。浏览器扩展只保存本机配对码。
- 菜单中的启停操作和界面设置不含遥测。仓库、打包脚本和 Release 均无需开发者的测试密钥。可用自己的 Key 在托盘验证，也可以运行 `python scripts/probe_deepseek.py`，在隐藏输入提示中测试真实连接、校对及重写，测试结束即丢弃 Key。

## 在 Mac 和 Windows 共用源码

要求 Python 3.11 或以上，macOS 13 或以上，或 Windows 10/11 x64。开发建议使用 Python 3.11。源码版和发布版共用 UI、模型请求、建议匹配和防过期逻辑。两端分别通过 macOS Accessibility 和 Windows UI Automation 访问文本控件。浏览器与 Electron 编辑器的支持取决于它们向平台暴露的焦点、值、范围坐标和可写属性。安全桌面、系统授权窗口和部分独占全屏应用由系统控制悬浮层。

**在 Mac 上开发或运行**

```sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-build.txt
python main.py
```

**离线测试与打包**

```sh
QT_QPA_PLATFORM=minimal python -m unittest discover -s tests -v
QT_QPA_PLATFORM=minimal python main.py --self-test
python scripts/build.py
```

Mac 构建生成 `dist/WhiteDot.app` 和 `dist/WhiteDot-macos-<架构>.zip`。Windows 构建生成 `dist/WhiteDot-windows-x64.exe`。构建脚本会运行打包程序的离线自检。Mac 可以编写两个平台的代码，Windows EXE 由 Windows 主机或仓库的 Windows runner 生成。Windows 端的创建环境、运行、调试和可直接交给 AI 代理的验收清单见 [Windows 调试与发布](docs/WINDOWS.md)。

## 用 VS Code 发布到 GitHub

1. 用 VS Code **打开当前 README 所在的 WhiteDot 文件夹**。此层目录直接包含隐藏的 `.github/workflows/release.yml`。把这一层作为仓库根目录，GitHub 才会识别发布工作流。
2. 在「源代码管理」选择 **Publish to GitHub / 发布到 GitHub**，登录并选择 **Public**。源码管理视图也可能显示 **Publish Branch / 发布分支**。如果已绑定其他远程，以 VS Code 显示的目标仓库为准。
3. 在仓库 **Actions → Build desktop releases → Run workflow** 手动构建。填写版本标签（例如 `v0.1.0`）可发布Mac 应用、Windows EXE、浏览器扩展和 SHA-256 校验表。留空可先在该次运行的 Artifacts 中试用。平时推送 `v*` 标签也会触发双平台发布。
4. Windows 电脑通过 VS Code 的 **Git: Clone** 打开同一仓库。提交平台修复后，Mac 上使用「同步更改」即可取得新版。构建产物、虚拟环境和本地设置已排除在 Git 之外。

## 需求依据与实现入口

Grammarly 官方指南描述了词或短语下划线、建议卡、点击采纳以及可移动悬浮控件。WhiteDot 采用这些交互，并为难以接入的应用提供同一套手动校对流程。[Grammarly 桌面指南](https://support.grammarly.com/hc/en-us/articles/4412816078349-Grammarly-for-Windows-and-Grammarly-for-Mac-user-guide) · [浏览器扩展指南](https://support.grammarly.com/hc/en-us/articles/115000091592-Grammarly-s-browser-extension-user-guide)

| 改动位置 | 职责 |
| --- | --- |
| `whitedot/app.py`、`windows_ui.py` | 焦点切换、白点和红线、建议选择、手动编辑器、重写与复制 |
| `whitedot/platforms/` | 编辑框识别、可见词坐标、替换前验证；对外统一使用 Unicode 码点和 Qt 屏幕逻辑坐标 |
| `whitedot/provider.py`、`settings.py` | 模型协议、结构校验、错误处理、系统密钥存储 |
| `whitedot/startup.py` | macOS 用户 LaunchAgent 与 Windows 当前用户 Run 项 |
| `tests/`、`scripts/` | 离线回归测试、浏览器样例、真实接口测试和打包 |
| `.github/workflows/release.yml` | 双平台构建及发布 |

现场验证结果和各应用的覆盖边界见 [初版验收记录](docs/VERIFICATION.md)。
