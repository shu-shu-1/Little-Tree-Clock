[English](README.en.md) | [简体中文](README.md)

# Little Tree Clock

Little Tree Clock is a feature-rich, highly customizable desktop clock application with a robust plugin ecosystem. It provides not only basic time display but also an integrated focus timer, advanced alarms, world clock, automation rules, and a highly flexible widget system.

## ✨ Core Features

- **Multi-mode Clock**: Includes world clock, stopwatch, countdown, and floating desktop widgets.
- **Focus Assistant**: Built-in Focus Timer to help you work and study efficiently.
- **Smart Alarms**: Supports custom ringtones, cycle loops, and rich automation trigger rules.
- **Plugin System**: Powerful plugin architecture that allows dynamic loading of third-party extensions (see [Plugin Guide](PLUGIN_GUIDE.md)).
- **Widget Layout**: Highly flexible widget engine supporting drag-and-drop layout and state persistence.
- **Time Sync**: Built-in NTP service to ensure precise time display.

## 🚀 Quick Start

This project is built using Python. We recommend using the [uv](https://github.com/astral-sh/uv) package manager.

### 1. Prerequisites
- Please ensure Python 3.10 or higher is installed.
- We recommend installing the `uv` dependency management tool.

### 2. Run the Project
Execute the following command in the project root directory to start the clock:
```bash
uv run main.py
```

### 3. Build Executable
If you need to package the program as a standalone executable file (no Python environment required), run the built-in build script:
```bash
python build.py
```
The packaged output will be generated in the `build/` directory.

## 🤝 Contributing

We wholeheartedly welcome contributions of any kind, including but not limited to submitting Issues, suggesting new features, and opening Pull Requests.
Before contributing, please read our [Contributing Guidelines](CONTRIBUTING.en.md) and [Code of Conduct](CODE_OF_CONDUCT.en.md).

- Want to develop your own Little Tree Clock plugin? Check out the [Plugin Guide](PLUGIN_GUIDE.md).

## 🛡️ Security & Support

- Encountered bugs or need help? Check out our [Support Page](SUPPORT.en.md).
- If you discover any security vulnerabilities, please refer to our [Security Policy](SECURITY.en.md) to report security issues securely at `zsxiaoshu@outlook.com`.

## 📄 License

This project is licensed under the [GNU General Public License v3.0 (GPLv3)](LICENSE). Welcome to use, modify, and build together!