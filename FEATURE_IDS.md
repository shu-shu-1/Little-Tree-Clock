# Feature ID Reference / 权限功能 ID 参考

This document lists all feature IDs in the independent permission system.
本文档列出独立权限系统中的所有权限功能 ID。

**Source of truth / 信息来源:**
- Built-in / 内置: `app/services/permission_service.py` (`_register_builtin_items`)
- Plugin / 插件: Each plugin's `__init__.py` (`register_permission_item` calls)

---

## Built-in Feature IDs / 内置权限功能 ID

| Feature ID | Category | Default Access Level | Description / 描述 |
| --- | --- | --- | --- |
| debug.open | system | user | Open debug panel / 打开调试面板 |
| settings.modify | system | user | Modify application settings / 修改应用设置 |
| ntp.sync | system | user | Sync time via NTP server / 通过 NTP 服务器同步时间 |
| plugin.install | plugin | user | Import/install/update plugins / 导入/安装/更新插件 |
| plugin.manage | plugin | admin | Enable/disable/reload/delete plugins / 启用/禁用/重载/删除插件 |
| layout.edit | fullscreen-clock | user | Enter/leave layout edit mode / 进入/退出布局编辑模式 |
| layout.add_widget | fullscreen-clock | user | Add widget to layout / 向布局添加组件 |
| layout.edit_widget | fullscreen-clock | user | Edit widget configuration / 编辑组件配置 |
| layout.delete_widget | fullscreen-clock | user | Delete widget from layout / 从布局删除组件 |
| layout.import_export | fullscreen-clock | user | Import/export layout files / 导入/导出布局文件 |
| world_time.manage | fullscreen-clock | user | Add/remove world time zones / 添加/删除世界时区 |
| clock.alarm.manage | clock | user | Create/edit/delete alarms / 创建/编辑/删除闹钟 |
| clock.timer.manage | clock | user | Create/delete timers / 创建/删除计时器 |
| clock.stopwatch | clock | user | Start using the stopwatch / 开始使用秒表 |
| central.manage | central-control | admin | Manage central control settings and policy / 管理集控设置和策略 |
| permission.manage | permission | admin | Manage permission levels and auth methods / 管理权限等级与认证方式 |

---

## Plugin Feature IDs / 插件权限功能 ID

Plugins register these at runtime via `api.register_permission_item(...)`.
插件通过 `api.register_permission_item(...)` 在运行时注册这些权限项。

### hitokoto_widget

| Feature ID | Default Access Level | Description / 描述 |
| --- | --- | --- |
| plugin.hitokoto_widget.fetch_quote | user | Fetch random quote (network request) / 获取随机一言（网络请求） |

### document_viewer

| Feature ID | Default Access Level | Description / 描述 |
| --- | --- | --- |
| plugin.document_viewer.open_document | user | Open document files / 打开文档文件 |

### layout_presets

| Feature ID | Default Access Level | Description / 描述 |
| --- | --- | --- |
| plugin.layout_presets.manage_presets | user | Create/delete/rename layout presets / 管理布局预设（创建/删除/重命名） |
| plugin.layout_presets.apply_preset | user | Apply layout preset / 应用布局预设 |

### volume_report_viewer

| Feature ID | Default Access Level | Description / 描述 |
| --- | --- | --- |
| plugin.volume_report_viewer.import_report | user | Import volume report / 导入音量报告 |
| plugin.volume_report_viewer.export_report | user | Export volume report / 导出音量报告 |
| plugin.volume_report_viewer.delete_report | user | Delete volume report / 删除音量报告 |

### exam_panel

| Feature ID | Default Access Level | Description / 描述 |
| --- | --- | --- |
| plugin.exam_panel.manage_subjects | user | Manage exam subjects / 管理考试科目 |
| plugin.exam_panel.manage_bindings | user | Manage subject-widget bindings / 管理科目与组件的绑定 |
| plugin.exam_panel.manage_plans | user | Manage study plans / 管理学习计划 |

### volume_detector

| Feature ID | Default Access Level | Description / 描述 |
| --- | --- | --- |
| plugin.volume_detector.send_alert | user | Send volume alert notification / 发送音量告警通知 |
| plugin.volume_detector.trigger_automation | user | Trigger volume automation / 触发音量自动化动作 |

### study_schedule

| Feature ID | Default Access Level | Description / 描述 |
| --- | --- | --- |
| plugin.study_schedule.manage_groups | user | Manage study plan groups / 管理学习计划分组 |
| plugin.study_schedule.manage_items | user | Manage study plan items / 管理学习计划条目 |
| plugin.study_schedule.manage_target_zone | user | Set target focus duration / 设置目标专注时长 |

---

## Notes / 备注

- Only feature IDs with actual `ensure_access` call sites in host code are registered; entries without an enforcement path are intentionally not listed.
  只有在宿主代码中存在 `ensure_access` 调用点的功能 ID 才会注册；没有校验路径的项不会出现在权限管理界面中。

- If no login method is enabled for any level, features at user/admin levels can be used without login by design — including the case where a password is set but its login method is not enabled.
  只要没有任何等级启用登录方式，user/admin 级别的功能按设计可无需登录直接使用——包括“设置了密码但未启用登录方式”的情况。

- Once a login method is enabled for any level, a level with no enabled login methods is **denied by default** — except `permission.manage`, which stays reachable so the configuration can be repaired.
  一旦任一等级启用了登录方式，未启用任何登录方式的等级将默认拒绝访问；`permission.manage` 例外，保证管理员始终能进入权限管理修复配置。

- Feature blocking by central control can still deny access even when user session level is sufficient; if the blocker callback fails, access is treated as blocked (fail-closed).
  集控的权限拦截可以在用户会话级别足够时仍然拒绝访问；blocker 回调异常时同样按受限处理（fail-closed）。

- Unknown or empty feature keys passed to `ensure_access` are denied and logged.
  传给 `ensure_access` 的未知或空 feature key 会被拒绝并记录日志。

- Plugins receive a `PluginPermissionFacade` (verification/registration/read-only queries only), never the raw service, so they cannot modify permission levels, auth methods, or passwords.
  插件拿到的是 `PluginPermissionFacade` 门面（仅校验/注册/只读查询），拿不到原始服务，因此无法修改权限等级、登录方式或密码。

- Plugin feature IDs are registered at runtime; the tables above reflect what each plugin currently registers. Plugin keys cannot collide with built-in keys or other plugins' keys.
  插件权限功能 ID 在运行时注册；上表反映了各插件当前注册的内容。插件 key 不允许与内置项或其它插件的 key 冲突。

- When in layout edit mode (`layout.edit`), sub-operations like `layout.add_widget`, `layout.edit_widget`, etc. do not require re-authorization.
  处于布局编辑模式时（`layout.edit` 已授权），子操作如 `layout.add_widget`、`layout.edit_widget` 等不需要重新授权。
