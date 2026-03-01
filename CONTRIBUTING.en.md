[English](CONTRIBUTING.en.md) | [简体中文](CONTRIBUTING.md)

# Contributing Guidelines

First of all, thank you for considering contributing to **Little-Tree-Clock**! It's people like you that make this open-source project better and better.

Whether it's reporting bugs, suggesting new features, updating documentation, or submitting code fixes, we highly welcome it.

## 💡 How to Contribute

### Submit an Issue
If you find a bug or have an idea for a new feature, please submit it on our GitHub Issues page:
- **Reporting a Bug**: Please provide reproduction steps, your OS, Python version, and error logs to ensure we can reproduce the issue.
- **Feature Request**: Explicitly describe the desired feature and its practical use case.

### Plugin Development
This project supports a rich plugin ecosystem. If you want to add specific functionality to the main program, **we strongly recommend developing a plugin first**, rather than modifying the main branch code.
This keeps the main program lightweight and decoupled.
For more details on writing a plugin, please check the [Plugin Guide](PLUGIN_GUIDE.md).

### Submitting a Pull Request (PR)

If you plan to directly modify the code and submit a PR, please follow this workflow:

1. **Fork this repository** to your personal account.
2. **Clone** the forked repository locally:
   ```bash
   git clone https://github.com/<your-username>/Little-Tree-Clock.git
   ```
3. **Create a branch** for your modifications:
   ```bash
   git checkout -b feature/your-feature-name
   # OR
   git checkout -b fix/your-bug-fix
   ```
4. **Install dependencies**: We recommend using `uv` to stay consistent with the project.
5. **Commit changes**: Ensure your commit message is concise and explains the purpose of the changes.
6. **Push to remote**:
   ```bash
   git push origin feature/your-feature-name
   ```
7. **Open a Pull Request** on the GitHub page, explaining your modifications, motivation, and any linked Issue.

## 🛠 Development Standards

- **Code Style**: This project uses Python. Please follow the PEP 8 style guide where possible.
- **Naming Conventions**: Files and modules generally use snake_case. Class names use PascalCase.
- **Module Structure**: Place any newly added features in reasonable subdirectories under `app/` (e.g., `app/models/`, `app/views/`, `app/services/`).
- **Testing**: Before committing code, ensure it runs correctly locally (running `uv run main.py` should throw no errors).

## 🤝 Need Help?
If you have any questions during the contribution process, feel free to leave a comment in the Issue or Discussions section, or contact us at zsxiaoshu@outlook.com. We will answer as soon as possible!
