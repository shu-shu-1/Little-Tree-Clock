# Plugin CLI

A small plugin development CLI for Little Tree Clock.

## Commands

1. Create scaffold

```bash
python tools/plugin_cli/cli.py init my_plugin --name "My Plugin"
```

2. Validate plugin folder

```bash
python tools/plugin_cli/cli.py validate plugins_ext/my_plugin
```

3. Package plugin

```bash
python tools/plugin_cli/cli.py pack plugins_ext/my_plugin --verify
```

4. Validate package file

```bash
python tools/plugin_cli/cli.py validate my_plugin.ltcplugin
```

## Notes

- Package format is `.ltcplugin` (ZIP payload).
- `init` generates `plugin.json`, `__init__.py`, `requirements.txt`, and `README.md`.
- `pack` validates source folder first.
- `validate` can check both folder and package.
