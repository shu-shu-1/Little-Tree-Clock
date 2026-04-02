# Feature ID Reference

This document lists all built-in feature IDs in the independent permission system.

Source of truth:
- app/services/permission_service.py (`_register_builtin_items`)

## Built-in Feature IDs

| Feature ID | Category | Default Access Level | Purpose |
| --- | --- | --- | --- |
| debug.open | system | user | Open debug panel |
| settings.modify | system | user | Modify application settings |
| plugin.install | plugin | user | Import/install/update plugins |
| plugin.manage | plugin | admin | Enable/disable/reload/delete plugins |
| layout.edit | fullscreen-clock | user | Enter/leave layout edit mode |
| layout.add_widget | fullscreen-clock | user | Add widget to layout |
| layout.edit_widget | fullscreen-clock | user | Edit widget configuration |
| layout.delete_widget | fullscreen-clock | user | Delete widget from layout |
| layout.import_export | fullscreen-clock | user | Import/export layout files |
| world_time.manage | fullscreen-clock | user | Add/remove world time zones |
| central.manage | central-control | admin | Manage central control settings and policy |
| permission.manage | permission | admin | Manage permission levels and auth methods |

## Dynamic Feature IDs (Plugin Extensions)

Plugins can register extra feature IDs at runtime via:
- Plugin API: `register_permission_item(...)`
- Service API: `PermissionService.register_plugin_permission_item(...)`

These IDs are dynamic and are not fixed in code.

Recommended naming convention:
- `<plugin_id>.<domain>.<action>`
- Example: `exam_panel.layout.lock`

## Notes

- If no auth method is configured for user/admin levels, features at that level can be used without login by design.
- Feature blocking by central control can still deny access even when user session level is sufficient.
