# Windows 便携版与开发交接

## 运行与升级

从当前版本的 GitHub Release 下载 `WhiteDot-windows-x64.exe`，放入固定文件夹并双击。运行时会在任务栏通知区域显示图标，屏幕右侧会出现可以拖动的白点。打包程序携带 Python 和 Qt，首次启动可能需要几秒。

升级旧版时，先从托盘退出正在运行的 WhiteDot，再替换原位置的 EXE。桌面程序沿用当前 Windows 账户的模型配置、凭据和白点位置。若曾手动加载旧版 WhiteDot 浏览器扩展，可在浏览器的扩展管理页面移除。已启用登录启动且调整过 EXE 位置时，在托盘中关闭再打开该选项，以更新启动路径。

1. 右键白点或托盘图标，打开 AI 服务设置。选择服务商、地址和模型，填入自己的 API Key 并验证。验证将向所选服务提交一个固定英文样例。
2. 点击白点打开编辑器，输入或粘贴英文。例如 `She go to teh library every day.`。停顿后会触发校对，点击有红色下划线的词查看并应用建议。
3. 需要整段修改时使用重写操作，核对结果后复制。收起后再打开可继续编辑这一轮运行的草稿。
4. 完成后可以收起白点面板。桌面程序只在自己的面板内接收输入，其他应用可继续使用自己的校对工具。

API Key 保存在 Windows 凭据管理器中。普通偏好位于 `%APPDATA%\WhiteDot\settings.json`。Release 提供 SHA-256 校验表，可在 PowerShell 中运行 `Get-FileHash .\WhiteDot-windows-x64.exe` 进行比对。当前构建流程生成未进行 Authenticode 签名的 EXE。

## 从源码运行

在 Windows x64 安装 Python 3.11，用 VS Code 打开包含 `main.py` 和 `WhiteDot.spec` 的项目根目录。在 PowerShell 中执行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py --self-test
.\.venv\Scripts\python.exe main.py
```

构建前，先通过托盘退出从 `dist` 运行的旧程序。以下命令生成单文件便携版，并在打包产物上执行离线自检。

```powershell
.\.venv\Scripts\python.exe scripts\build.py
```

输出文件为 `dist\WhiteDot-windows-x64.exe`。在普通 Windows 用户账号中可直接运行。

## 实机验收

| 场景 | 检查方法 |
| --- | --- |
| 白点 | 在明、暗壁纸上观察白点与阴影是否同心。拖动到另一台显示器，退出后重开，确认位置恢复。 |
| 开始输入 | 在其他软件中打字，随后点击白点，应打开独立编辑器并能立即输入。 |
| 词级修改 | 在面板内输入 `🙂 I saw teh cat.`。等校对完成后点开错词，选择 `the`，确认 emoji 和其余文字保留。 |
| 前后版本 | 在等待校对或重写时继续修改正文，确认旧结果不会盖掉新内容。 |
| 复制 | 检查空文本时复制按钮状态，然后分别复制非空原文和重写结果，在记事本中核对。 |
| 窗口 | 核对靠近屏幕四边、100% 与 150% 缩放、跨显示器移动时，面板与操作按钮可见。 |
| 托盘 | 打开模型设置并验证一次错误 Key，确认显示错误且上次有效配置仍可使用。切换登录启动并重新登录验收。 |

共享 UI 在 `whitedot/windows_ui.py`，面板状态和后台任务在 `whitedot/app.py`。服务商兼容和凭据存储分别在 `whitedot/provider.py`、`whitedot/settings.py`。调整登录启动时检查 `whitedot/startup.py`。

可直接交给 Windows 端 AI 代理的任务：

> 按 docs/WINDOWS.md 从源码运行 WhiteDot、执行离线测试并构建 x64 便携 EXE。用合成样例检查白点在不同背景和缩放下的视觉效果，以及编辑器输入、建议替换、重写、复制和草稿收起再打开的流程。由我在程序中输入模型密钥。记录 Windows 版本、屏幕缩放和可复现步骤，修复后运行同一套测试与打包命令。

## 发布到 GitHub

1. 在 VS Code 将本轮修改同步到已配置的 GitHub 仓库。
2. 打开仓库的 **Actions → Build desktop releases → Run workflow**，选择已同步的分支。将 **Optional release tag** 留空可先生成 Actions Artifacts。
3. 确认试用通过后，填写新的版本标签（例如 `v0.2.0`）并运行。两个平台都构建成功后，工作流把 macOS ZIP、Windows 便携 EXE 和 SHA-256 校验表上传至同一 Release。向远程推送版本标签也可触发发布。
4. macOS 上可以开发共享源码。Windows EXE 在 Windows 本机或同一仓库的 Windows runner 上构建。
