# 本地任务队列 v1

仅限本机当前 Windows 用户既有文件权限，无端口、HTTP、凭据、系统服务、邮件发送或云同步。软件运行时每秒检查，最多每轮4条；退出时保留请求，下次启动处理。排队成功不代表任务写入成功，必须读取回执。

## 正式实例

根目录：`C:\path\to\SiteTaskAI-windows-x64`

- 正式数据库：`data\sitetask.db`
- 请求：`data\integration\inbox\<command_id>.json`
- 回执：`data\integration\receipts\<command_id>.json`
- 已处理原始请求：`data\integration\archive`
- 无效请求：`data\integration\rejected`
- 心跳：`data\integration\health.json`（检查 checked_at 是否新鲜、pid 是否在运行）
- 启用配置：`config\local_queue.json`，内容 `{"enabled":true,"version":1}`；设 enabled 为 false 可暂停消费。已有请求不会删除。
- 单实例消费锁：`data\integration\consumer.lock`。不要手工删除正在使用的锁。
- 标准库 CLI：`tools\task_queue.py`，Python 3.12+。开发源码对应 `scripts\task_queue.py`。

目录继承当前安装目录权限，不修改 ACL。相同账户下有目录写入权限的程序可以提交此协议允许的请求。

## 安全调用

```powershell
$taskRoot = 'C:\path\to\SiteTaskAI-windows-x64'
$taskPython = 'C:\path\to\sitetask-ai\.venv\Scripts\python.exe'
$taskClient = Join-Path $taskRoot 'tools\task_queue.py'
& $taskPython -B $taskClient --root $taskRoot health
& $taskPython -B $taskClient --root $taskRoot read --source-reference 'PROJECT:T008'
& $taskPython -B $taskClient --root $taskRoot submit 'C:\path\reviewed-command.json'
& $taskPython -B $taskClient --root $taskRoot status '<提交的UUID>'
```

`read` 直接使用 SQLite `mode=ro` 与 `query_only`，可在线读取全部当前状态，不运行迁移、不写库。省略 source-reference 返回全部任务。每个结果含 `task` 和 `revision`（整行 SHA-256）。晨报和邮件跟进应每次读取当前状态，不能用历史回执推断当前完成状态。

`ping` 生成并提交一个只检查通信的命令，返回 UUID；再用 status 核实 `ok`。ping 只记队列回执，不创建任务。health 可能是上次运行留下的文件，必须核对时间和进程。

## JSON 协议

UTF-8 JSON，最大32768字节；禁止重复键、未知字段及类型隐式转换。command_id 为规范小写 UUID，同一次逻辑请求重试必须保留相同 UUID 和相同内容。不得手工逐字写入 `.json` 文件；CLI 先写临时文件、flush/fsync，再原子发布完整请求。

新增示例（示例不提交到正式库）：

```json
{
  "version": 1,
  "command_id": "8d309694-9844-48c8-90df-804f85a00bcc",
  "operation": "create",
  "source_reference": "PROJECT:stable-business-key",
  "fields": {
    "title": "确认检查安排",
    "description": "要求：确认检查日期及结果。\n时间：申请时间待顾问确认。\n相关人员：工程师 / 监理。\n\n来源邮件：\nhttps://mail.google.com/mail/u/0/#all/example",
    "due_date": "2026-10-08",
    "no_due": false,
    "category": "IRF",
    "priority": "normal"
  }
}
```

`create` 的6个 fields 必填；`update` 的 fields 为非空子集，必须另有顶层 `expected_revision`。`due_date` 与 `no_due` 必须一起提供；No Due 使用 `no_due:true,due_date:null`。日期格式严格 YYYY-MM-DD。更新正文示例：

```json
{
  "version": 1,
  "command_id": "2a21a779-72bf-4eb6-94e0-1378ee30594a",
  "operation": "update",
  "source_reference": "PROJECT:stable-business-key",
  "expected_revision": "用read或get返回的64位revision替换",
  "fields": {"description": "要求：新的已核实事项。\n时间：待确认。\n相关人员：工程师。"}
}
```

其他操作：`get` 只含 version、command_id、operation、source_reference；`ping` 只含前三项。

字段约束：标题1–200字符，首尾无空白、无换行，不加 PROJECT 前缀；说明最多6000字符。category：Site Inspection / IRF / EFI / Drawing / Method Statement / Material / Email / Meeting / Report / Follow-up / Personal / Other。priority：low / normal / high / urgent。source_reference：`PROJECT:` 加1–160位 ASCII 字母、数字、冒号、点、下划线或短横线，首位字母/数字。

说明由已核实内容编写，保持简洁；来源放最后 `\n\n来源邮件：\n`，每行一个 HTTPS 链接，现有悬停界面显示为可点击“查看原邮件”。协议不自动概括或推断邮件，不发出网络请求。

## 去重、冲突和保护

- command_id 与规范化内容摘要存入 `local_queue_commands`。同ID同内容返回原回执；同ID不同内容返回冲突。任务变更与回执在同一SQLite事务，提交后文件回执失败会自动重建。
- source_reference 独立去重。同来源 create 返回 existing，不覆盖任何字段；来源不唯一返回 conflict。不会根据标题猜测合并，调用方必须沿用已有稳定来源键。
- 只更新 pending。completed/cancelled 返回 protected，全部字段保持原样。禁止写 status/completed_at/id/source/source_reference/created_at、禁止删除或恢复。
- `local_queue_sources` 保留关联和删除标记，删除后不因旧邮件再建。历史排除 T002、T003、T004、T013 永久返回 protected。
- 更新在事务中检查整行 revision；有更改则 conflict。已关联任务还比较上次队列写入的基线：即使调用方刚重新读取，也不会覆盖其后发生的手工改动。冲突没有 force 参数，须人工核对；不要自动换UUID反复尝试覆盖。
- 迁移4只增加队列账本、关联表和删除触发器，为已有来源建立版本基线，不改变现有任务字段。
- 编辑器、预览、模态窗、菜单、鼠标操作或短暂撤销期中暂停消费；活跃输入草稿也暂停。关闭编辑器后重新检查 revision。处理后刷新主界面和All Tasks，保留All Tasks选中任务。
- V1禁止 due_time，防止邮件计划静默成为定时提醒。仅改标题/说明保留原来的时刻和通知记录；明确改日期/No Due则清空时刻，并按现有Repository规则清理旧提醒记录。
- 本地程序执行任务操作，不支持SQL、文件路径、shell命令、代码或网络请求。请求路径拒绝symlink/junction/reparse point。

## 回执及限制

状态：created、updated、existing、found、not_found、protected、conflict、invalid、ok。回执含 command_id、payload_sha256、processed_at；适用时含完整 task 和 revision；冲突/保护有 reason。queued/no_receipt 不是成功。遇到conflict/protected停止自动写入，报告原因。

请求无业务顺序保证：依赖操作必须等前一条成功并使用最新revision。只支持一条命令一个任务，无批量部分提交。软件关闭/休眠/正在编辑时会延迟。I/O错误保留请求待重试，health显示retrying状态；不清空队列和历史账本。应用恢复备份时须同时保存数据库、队列和回执，不能仅删除账本重新投递。

## 验证和回退

隔离库覆盖新增、更新、严格校验、重复ID/来源、已完成/取消/删除保护、人工版本冲突、数据库锁忙、事务失败回滚、提交后回执失败恢复、双消费者锁、迁移保留原数据、真实Qt事件循环与外部CLI提交、编辑时暂停和界面刷新。

部署前退出应用、SQLite一致快照、原程序和源码备份。启动必须通过 scripts/verify_bundle.py ICU/QtCore加载门禁，再核实可见主窗口和队列ping回执。正式库不插入测试任务，只做ping。数据验收比较备份中所有任务的全部字段。

回退：正常退出，先将local_queue.json设为disabled并保留队列内容，再恢复备份程序；不要在已有新任务后直接覆盖旧数据库。旧版可忽略新增账本表，但不能消费队列。任何恢复操作先做新的完整备份。
