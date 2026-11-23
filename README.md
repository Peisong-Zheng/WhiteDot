# WhiteDot 白点英文校对

WhiteDot 是 macOS 和 Windows 上的悬浮英文编辑器。点一下白点，写或粘贴一段英文，停顿后就会出现拼写和语法建议。收起时屏幕上只留一个可拖动的白点。

![WhiteDot 编辑器中的原文、红线、整段重写和悬浮白点](docs/editor.png)

## 开始使用

1. **macOS** 下载发行页的 `WhiteDot-macos-arm64.zip`，解压，把 `WhiteDot.app` 放到「应用程序」后打开。该包适用于 Apple 芯片 Mac，采用 ad-hoc 签名。Intel Mac 可以在本机从源码运行和打包。
2. **Windows x64** 下载 `WhiteDot-windows-x64.exe`，放在固定位置后双击即可运行。程序图标位于任务栏通知区域，可能在向上箭头内。
3. 点白点，打开右上角的设置按钮。选择服务商和模型，填写自己的 API Key，点 **验证并保存**。程序会发送一个固定英文例句，检查密钥和模型能否处理校对请求。
4. 在编辑器中输入英文，停顿约 0.9 秒后会发起校对。点击红色波浪线下的词，查看原因并选择替换词。要修改整个段落，点 **语法重写**。下方会展开结果，原文和结果都可以单独复制。

| 操作 | 用法 |
| --- | --- |
| 打开或收起 | 点击白点；在编辑器内也可按 Esc 收起。 |
| 整段重写 | Mac 按 ⌘ Return，Windows 按 Ctrl+Enter。 |
| 移动白点 | 按住并拖动。下次启动时恢复位置。 |
| 登录时启动 | 右键白点、菜单栏或系统托盘图标，勾选「登录时启动」。 |
| 返回草稿 | 再点白点即可接着写。草稿和已完成的结果保存在本次运行的内存中，退出应用前请复制需要保留的文字。 |

## 从 0.1 升级

如果旧版正在运行，先复制需要保留的草稿，从它的托盘菜单退出，然后打开新版。两个版本共用模型配置、系统凭据和白点位置。0.2 起，WhiteDot 只处理手动放进自己编辑器的正文，辅助功能权限、桌面文字监控和浏览器配对已移除。如果曾在浏览器中手动安装 0.1 的 WhiteDot 扩展，可在扩展管理页面将它移除。Mac 端也可以在系统设置中撤销旧版权限。

## 模型与隐私

DeepSeek 预置为关闭推理，密钥验证、自动校对、整段重写均会携带 `thinking.type = disabled`。还提供 OpenAI、Gemini 和兼容 OpenAI Chat Completions 的自定义服务设置，模型和地址可编辑。服务商需要支持提示中规定的 JSON 输出。模型请求按所选服务商规则计费。[DeepSeek 官方说明](https://api-docs.deepseek.com/guides/thinking_mode/)

可校对的草稿按整段发送至所选服务，中英混排也会发送整段。每次最多 24,000 个字符。收起会取消等待发送的检查；如果请求已经发出，旧结果会被丢弃。修改原文也会使先前的建议失效。重写要求尽量保留原意和措辞，并在本地校验段落结构。

Key 保存在 macOS 钥匙串或 Windows 凭据管理器中。普通设置位于 `~/Library/Application Support/WhiteDot/settings.json` 或 `%APPDATA%\WhiteDot\settings.json`。项目只分发程序、字体及其许可证，首次使用需验证自己的密钥。

## 开发与发布

源码支持 Python 3.11+、macOS 13+ 和 Windows 10/11 x64。在 Mac 上可使用以下命令。Windows 的环境搭建、便携 EXE 打包与交给 AI 代理的测试清单见 [Windows 交接说明](docs/WINDOWS.md)。

```sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-build.txt
python main.py
```

```sh
QT_QPA_PLATFORM=minimal python -m unittest discover -s tests -v
QT_QPA_PLATFORM=minimal python main.py --self-test
python scripts/build.py
```

`whitedot/windows_ui.py` 是两个系统共用的白点和编辑器；`whitedot/app.py` 管理输入、请求、过期结果和菜单；`whitedot/provider.py` 与 `settings.py` 管理服务协议及凭据。英文字体 Spectral 随程序离线提供。[字体来源](https://github.com/google/fonts/tree/main/ofl/spectral) · [字体许可证](whitedot/assets/OFL.txt)

项目根目录直接包含 `.github/workflows/release.yml`。在 VS Code 同步源码后，打开 GitHub 的 **Actions → Build desktop releases → Run workflow**。留空版本号可试构建，填写新标签（如 `v0.2.0`）可发布。工作流分别在 macOS 和 Windows 构建，双端通过后会上传 Mac 压缩包、Windows 便携 EXE 及 SHA-256 校验表。[本版验收记录](docs/VERIFICATION.md)
