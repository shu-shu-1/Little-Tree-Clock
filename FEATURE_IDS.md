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
| settings.view | system | user | View application settings / 查看应用设置 |
| ntp.sync | system | user | Sync time via NTP server / 通过 NTP 服务器同步时间 |
| plugin.install | plugin | user | Import/install/update plugins / 导入/安装/更新插件 |
| plugin.manage | plugin | admin | Enable/disable/reload/delete plugins / 启用/禁用/重载/删除插件 |
| plugin.configure | plugin | user | Configure individual plugin settings / 配置单个插件设置 |
| layout.edit | fullscreen-clock | user | Enter/leave layout edit mode / 进入/退出布局编辑模式 |
| layout.add_widget | fullscreen-clock | user | Add widget to layout / 向布局添加组件 |
| layout.edit_widget | fullscreen-clock | user | Edit widget configuration / 编辑组件配置 |
| layout.delete_widget | fullscreen-clock | user | Delete widget from layout / 从布局删除组件 |
| layout.import_export | fullscreen-clock | user | Import/export layout files / 导入/导出布局文件 |
| layout.save | fullscreen-clock | user | Save layout changes / 保存布局更改 |
| widget.group | fullscreen-clock | user | Group/ungroup widgets / 组件分组/解组 |
| widget.detach | fullscreen-clock | user | Detach widget to floating window / 将组件分离为浮动窗口 |
| widget.float | fullscreen-clock | user | Float widget as always-on-top / 将组件置顶显示 |
| world_time.manage | fullscreen-clock | user | Add/remove world time zones / 添加/删除世界时区 |
| clock.alarm.manage | clock | user | Create/edit/delete alarms / 创建/编辑/删除闹钟 |
| clock.alarm.trigger | clock | user | Alarm notification actions / 闹钟通知动作 |
| clock.timer.manage | clock | user | Create/edit/delete timers / 创建/编辑/删除计时器 |
| clock.stopwatch | clock | user | Use stopwatch feature / 使用秒表功能 |
| calendar.event.manage | calendar | user | Create/edit/delete calendar events / 创建/编辑/删除日历事件 |
| notification.send | notification | user | Send system notifications / 发送系统通知 |
| notification.configure | notification | user | Configure notification settings / 配置通知设置 |
| central.manage | central-control | admin | Manage central control settings and policy / 管理集控设置和策略 |
| permission.manage | permission | admin | Manage permission levels and auth methods / 管理权限等级和认证方式 |
| auth.login | auth | user | Login/authenticate session / 登录/认证会话 |
| auth.logout | auth | user | Logout/end session / 登出/结束会话 |
| file.import | file | user | Import files into the app / 将文件导入应用 |
| file.export | file | user | Export files from the app / 从应用导出文件 |
| window.fullscreen | window | user | Enter/exit fullscreen mode / 进入/退出全屏模式 |
| window.always_on_top | window | user | Toggle always-on-top for windows / 切换窗口置顶状态 |
| network.request | network | user | Make HTTP network requests / 发起网络请求 |

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

- If no auth method is configured for user/admin levels, features at that level can be used without login by design.
  如果未配置 user/admin 级别的认证方式，按设计该级别的功能可无需登录直接使用。

- Feature blocking by central control can still deny access even when user session level is sufficient.
  集控的权限拦截可以在用户会话级别足够时仍然拒绝访问。

- Plugin feature IDs are registered at runtime; the tables above reflect what each plugin currently registers.
  插件权限功能 ID 在运行时注册；上表反映了各插件当前注册的内容。

- When in layout edit mode (`layout.edit`), sub-operations like `layout.add_widget`, `layout.edit_widget`, etc. do not require re-authorization.
  处于布局编辑模式时（`layout.edit` 已授权），子操作如 `layout.add_widget`、`layout.edit_widget` 等不需要重新授权。
