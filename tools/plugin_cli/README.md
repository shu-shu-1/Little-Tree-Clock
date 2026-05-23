# Plugin CLI

A small plugin development CLI for Little Tree Clock.

## Commands

1. Create scaffold

```bash
python tools/plugin_cli/cli.py init my_plugin --name "My Plugin"
```

With all options:

```bash
python tools/plugin_cli/cli.py init my_plugin \
  --name "My Plugin" \
  --author "Author <email>" \
  --description "Plugin description" \
  --version "1.0.0" \
  --plugin-type feature \
  --homepage "https://github.com/author/my_plugin" \
  --min-host-version "0.10.3" \
  --icon "assets/icon.png" \
  --require "other_plugin" \
  --dependency "requests>=2.31" \
  --permission network \
  --tag notification \
  --output-dir plugins_ext \
  --force
```

2. Validate plugin folder

```bash
python tools/plugin_cli/cli.py validate plugins_ext/my_plugin
```

Strict mode (treats warnings as failures):

```bash
python tools/plugin_cli/cli.py validate plugins_ext/my_plugin --strict-warnings
```

JSON output:

```bash
python tools/plugin_cli/cli.py validate plugins_ext/my_plugin --json
```

3. Package plugin

```bash
python tools/plugin_cli/cli.py pack plugins_ext/my_plugin --verify
```

Specify output path:

```bash
python tools/plugin_cli/cli.py pack plugins_ext/my_plugin -o dist/my_plugin-1.0.0.ltcplugin --force
```

4. Validate package file

```bash
python tools/plugin_cli/cli.py validate my_plugin.ltcplugin
```

## Validation Rules

The `validate` command checks:

| Field | Rule |
|-------|------|
| `id` | Required, must match `^[a-z][a-z0-9_]{0,63}$` |
| `name` / `name_i18n` | At least one must provide a non-empty string |
| `plugin_type` | Must be `feature` or `library` |
| `version` | Warns if empty |
| `requires` | Each item must be a valid plugin ID |
| `dependencies` | Each item must be a safe PyPI requirement spec |
| `permissions` | Each item must be a known permission key |
| `name_i18n` / `description_i18n` | Must be `{lang: string}` dicts |
| `name` / `description` (as dict) | Same i18n validation |
| `homepage` | Warns if not a URL |
| `min_host_version` | Warns if not semver format |
| `icon` | Validates base64 / data URI payload |
| `tags` | Must be an array |

## Notes

- Package format is `.ltcplugin` (ZIP payload).
- `init` generates `plugin.json`, `__init__.py`, `requirements.txt`, and `README.md`.
- `pack` validates source folder first; use `--allow-warnings` to override.
- `validate` can check both folder and `.ltcplugin` package.
