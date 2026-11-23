# 初版验收记录

验证于 2026-11-23，在 Apple 芯片 Mac、macOS 26.4.1 和 Chrome 157 上完成。以下把真实桌面交互、模型接口测试和模拟控件回归分别记录，方便 Windows 端复查。

| 场景 | 本次结果 |
| --- | --- |
| DeepSeek 官方接口 | 通过应用的 Provider 验证密钥、执行逐项校对和整框重写。样例 `She go to teh library every day.` 得到 `She go → She goes`、`teh → the` 两条建议，重写为 `She goes to the library every day.`。三种调用均使用关闭推理的参数，使用一次性隐藏输入，只发送固定样例。 |
| 真机 AppKit 输入框 | 用鼠标点白点，结果窗出现后原应用仍保有焦点；再次点白点收起；点原应用红线，选中候选词并验证输入框实际变化。此项使用固定建议测试窗口与点击。 |
| Chrome 原生辅助功能 | 在独立配置中测试 HTML 单行输入、多行输入与含粗体的富文本。能捕获文本，为 emoji 后面的错词定位并在普通输入框写回。此版本的富文本控件未确认安全写回时，程序保留原格式，提供可复制的修正版。密码框排除，过期建议被拒绝。 |
| Chrome 扩展 | 在独立配置中实际加载 MV3 扩展，输入临时配对码，连接桌面端的真实本机接口。网页上的 `😀 fix teh word` 可点红线并变成 `😀 fix the word`。另测了滚动换行的 textarea、粗体与斜体、IME 组合输入、过期建议、密码框和付款字段。此项使用固定候选。 |
| 实际 Codex 应用 | 识别到运行中的 `com.openai.codex`，其 ProseMirror/TipTap 编辑器暴露可编辑的 `AXTextArea`、控件边界、范围坐标接口和可设置的选区。检查时焦点在 `AXGroup`，无法确认草稿为空，因此只读取控件元数据。真实草稿内的逐词点击与写回尚待验证。 |
| 手动编辑和设置 | Qt 回归验证了无可读目标时进入手动编辑、原文校对、显示上下两栏、按内容启用复制按钮、修改原文使旧结果失效，以及验证失败／取消时保留旧服务配置。另验证了白点坐标恢复、显示器断开后的回退和在隔离目录内添加、移除 macOS 登录项。 |
| Windows | 共享 UI、模型协议和 Windows 控件适配器的模拟测试通过。Windows 原生 UI Automation、实际托盘、登录启动、Edge 和 Codex 的真机验收留给 Windows 端。 |
| macOS 发布包 | 从打包后的 ZIP 重新解压，执行严格签名校验并用真实 Cocoa 窗口运行 `--self-test` 成功。签名为 ad-hoc。 |
| GitHub 发布 | 已提供双平台工作流、手动发布入口及校验文件生成逻辑。首次真实远程构建与公开 Release 需要将当前仓库发布到自己的 GitHub 账号后触发。 |

## 可复现检查

在开发虚拟环境中，从仓库根目录运行。自动桌面交互脚本会临时启动自己的测试窗口。请在有图形桌面、允许辅助功能并且方便短暂停止键鼠操作时运行这两条 Mac 命令。

```sh
QT_QPA_PLATFORM=minimal python -m unittest discover -s tests -v
python -m scripts.smoke_mac_chrome
python -m scripts.smoke_mac_panel
python tests/browser/run_dom.py
node --test tests/browser/worker.test.cjs
node tests/browser/run_extension.cjs
```

本次 Python 离线套件在 Mac 上共发现 43 项，42 项通过，Windows 原生 UI Automation 初始化检查按平台跳过。扩展 service worker 的三项 Node 测试通过。完整扩展联调和浏览器 DOM 测试需要已安装 Chrome；联调脚本使用自己的临时浏览器配置和本机端口。

需要复测模型时运行 `python scripts/probe_deepseek.py`，在隐藏提示中输入自己的密钥。需要验收 Windows 包时按 [Windows 实机调试与发布](WINDOWS.md) 操作。重启登录后的实际启动以及其他模型服务商均需在对应设备和账户下确认。
