[English](CONTRIBUTING.en.md) | [简体中文](CONTRIBUTING.md)

# 贡献指南 (Contributing)

首先，非常感谢您考虑为 **小树时钟 (Little-Tree-Clock)** 做出贡献！正是因为有开源社区的贡献，本项目才能不断进步和完善。

无论是报告 Bug、提出新功能建议、修改文档，还是提交代码修复，我们都非常欢迎。

## 💡 如何贡献

### 提出 Issue
如果您发现了 Bug 或有新功能的想法，请在 GitHub 的 Issues 页面提交：
- **报告 Bug**：请提供重现步骤、操作系统、Python版本以及错误日志，确保我们能复现该问题。
- **功能建议**：请清晰地描述所需功能及其实际使用场景。

### 插件开发
本项目支持丰富的插件生态。如果您想为主程序添加特定功能，**建议优先考虑开发插件**，而不仅是修改主分支代码。
这能保持主程序轻量且解耦。
关于如何编写插件，详情请查看：[插件开发指南](PLUGIN_GUIDE.md)。

### 提交代码 (Pull Request)

如果您打算直接修改代码并提交 PR，请遵循以下工作流：

1. **Fork 本仓库** 到您的个人账户中。
2. **克隆(Clone)** Fork 的代码库到本地：
   ```bash
   git clone https://github.com/<您的用户名>/Little-Tree-Clock.git
   ```
3. **创建分支(Branch)** 进行您的修改：
   ```bash
   git checkout -b feature/your-feature-name
   # 或者
   git checkout -b fix/your-bug-fix
   ```
4. **安装依赖**：建议使用 `uv` 从而与项目保持一致。
5. **提交更改**：请确保 commit message 简明扼要，说明更改的目的。
6. **推送到远程**：
   ```bash
   git push origin feature/your-feature-name
   ```
7. 在 GitHub 页面 **发起 Pull Request**，说明您的修改内容、动机以及相关联的 Issue。

## 🛠 开发规范

- **代码风格**：本项目使用 Python 开发。请尽量遵循 PEP 8 代码风格规范。
- **命名规范**：文件和模块大多采用 snake_case。类名使用 PascalCase。
- **模块结构**：新增加的功能请尽量放置在 `app/` 的合理子目录中（例如 `app/models/`, `app/views/`, `app/services/`）。
- **测试**：在提交代码前，请确保在本地测试运行能够正常工作（执行 `uv run main.py` 不抛出错误）。

## 🤝 遇到问题？
如果您在贡献过程中遇到任何疑问，欢迎在 Issue 或讨论区（Discussions）中留言提问，我们会尽快为您解答。
