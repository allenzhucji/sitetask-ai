# SiteTask AI

**A desktop task widget for construction site engineers, built with AI-assisted development (ChatGPT / Codex).**
**面向工程现场的桌面任务管理小程序，借助 AI 工具（ChatGPT / Codex）辅助开发。**

## About / 项目简介

**English**
SiteTask AI is a lightweight Windows widget for tracking inspection requests, drawing queries, method statements, material approvals, meeting actions and reports.

The application was developed with AI tools (ChatGPT, Codex), with human requirements, code review, testing and iteration.

- **Stack:** Python 3.12, PySide6 (Qt), SQLite, Pydantic, PyInstaller (Windows .exe)
- **Natural-language input:** "明天下午3点 检查 3F 钢筋" or "next Monday submit MS" is parsed locally into a dated task; low-confidence input can fall back to an AI API, always with a preview before saving
- **Local task queue:** separately authorised tools can submit tasks through a local JSON file queue with strict validation, de-duplication and completion protection. See [QUEUE_API.md](QUEUE_API.md).
- **Integration boundary:** this repository does not include a mailbox monitor, cloud API or remote task deletion. External integrations need their own configuration and privacy review.
- **Tests:** pytest coverage with mocked AI calls, plus a dependency-free repository privacy check

**中文**
SiteTask AI 是用于记录和跟踪验收申请、图纸疑问、施工方案、材料报审、会议行动项和报告的 Windows 桌面小组件。

代码借助 ChatGPT、Codex 等 AI 工具完成，并由人工提出需求、审阅代码、测试和迭代。

- **技术栈：** Python 3.12、PySide6（Qt）、SQLite、Pydantic、PyInstaller 打包为 Windows exe
- **自然语言录入：** 输入"明天下午3点 检查 3F 钢筋"即可在本地解析为带日期的任务；本地把握不大时可回退调用 API 接口，保存前均需预览确认
- **本地任务队列：** 经单独授权的外部工具可通过本地 JSON 文件队列提交任务，带严格字段校验、去重和已完成任务保护。见 [QUEUE_API.md](QUEUE_API.md)。
- **集成边界：** 本仓库不包含邮箱监控、云端接口或远程删除任务功能。外部集成需独立配置并审查隐私。
- **测试：** pytest 自动化覆盖，AI 调用使用 mock；另有无需应用依赖的仓库隐私检查

> Keep examples synthetic. Never commit runtime data, credentials or private project material. See [PRIVACY.md](PRIVACY.md) before contributing or sharing a build.
> 示例应使用虚构数据。不要提交运行数据、密钥或私人项目资料；提交代码或分享构建前请阅读 [PRIVACY.md](PRIVACY.md)。

---
## 详细说明（中文）

SiteTask AI 是面向 Windows 10/11 的个人桌面任务 Widget，主要服务于 IRF、EFI、现场检查、图纸审核、Method Statement、材料审批、邮件、会议行动项和报告等工程现场事项。

当前版本完成 V1、V1.5 和 V2。V3 及以后功能不在本版本范围内。

## 核心规则

- 任务可以保存为任意日期，不受三天范围限制。
- 主 Widget 只显示全部未完成逾期任务，以及今天、明天和后天的未完成任务。
- 晚于后天的任务保存在 SQLite，可在 All Tasks 的 Later 或 Upcoming 中查看和编辑。
- 远期任务进入三天范围后会在定时刷新时自动出现在主 Widget。
- 完成、取消或删除任务后不再通知。
- 自然语言任务无论由本地解析还是 AI 解析，都必须先预览并由用户确认。

## 已完成功能

### V1：桌面任务管理

- 无边框深色 Widget、拖动和边缘缩放
- 保存窗口位置、尺寸和固定状态
- 始终置顶图钉切换
- 系统托盘、关闭到托盘和托盘退出
- 当前用户级 Windows 开机启动
- Quick Task 和完整任务编辑器
- 默认折叠的 Quick Task/AI Task 输入栏和右下角展开按钮
- 任意未来日期、过去日期提示和全天任务
- Overdue、Today、Tomorrow、Day After Tomorrow 分组
- All Tasks 搜索及 Upcoming、Next 3 Days、Later、Overdue、Completed、All 筛选
- 编辑、删除、完成、恢复、复制、修改日期和完成撤销
- 50px 紧凑任务卡片；最小窗口可显示至少五条跨分组任务
- 双击任务卡直接打开编辑器
- 到期前一小时和到期时 Windows 通知
- SQLite 长期存储、恢复性设置文件和轮转日志

### V1.5：本地自然语言解析

- 中文：今天、明天、后天、星期、下周、上午、下午、晚上、下个月及明确日期
- 英文：today、tomorrow、weekday、next Monday、3pm、month/date 等表达
- 支持远期和跨年日期
- 自动清理标题、建议分类和优先级
- 默认时间、置信度、歧义提示和确认预览

### V2：AI 任务解析

- 本地解析优先，低置信度时按设置回退至 OpenAI
- Pydantic 结构化验证
- AI 不得虚构没有依据的日期
- 远期 AI 任务正常保存，不会被移动到三天内
- API Key 使用 Windows Credential Manager/keyring，环境变量作为回退
- AI 开关、模型配置和连接测试
- AI 失败或未配置时，手动任务和本地解析继续可用
- 自动化测试全部使用 mock，不调用收费 API

## Windows 构建版运行

1. 解压 `SiteTaskAI-windows-x64.zip` 到一个可写目录。
2. 保留 `SiteTaskAI.exe` 和 `_internal` 文件夹的相对位置。
3. 双击 `SiteTaskAI.exe`。
4. 首次运行会在程序目录创建 `config`、`data` 和 `logs`。

应用没有代码签名，Windows SmartScreen 可能显示未知发布者提示。请只运行从可信来源取得并核对过 SHA-256 的构建。

## 从源代码运行

要求：Windows 10/11 x64、Python 3.12+、Git。

```bat
scripts\setup.bat
scripts\run.bat
```

`setup.bat` 创建 `.venv` 并安装 `requirements.txt` 中的依赖。

## AI 配置

1. 打开 Settings。
2. 勾选 `Enable AI Parsing`。
3. 在 API Key 中输入 OpenAI API Key。
4. 在 Model 中输入可用的 OpenAI 模型 ID。
5. 点击 `Test Connection`。
6. 保存设置。

API Key 保存位置：

- 首选：Windows Credential Manager/keyring
- Service Name：`SiteTaskAI`
- Username：`openai_api_key`
- 回退：`OPENAI_API_KEY` 环境变量

API Key 不写入 `settings.json`、Git、数据库或普通日志。日志格式化器会对常见 API Key 形式进行脱敏。

### 无 API Key 模式

没有 API Key 时应用仍可正常启动，并支持：

- 手动创建和编辑任务
- Quick Task
- 本地自然语言解析
- All Tasks、搜索和筛选
- 固定、托盘、通知和开机启动

只有需要 AI 回退的解析不可用，界面会提示尚未配置。

## 数据位置

打包版以 `SiteTaskAI.exe` 所在目录为根目录；源代码运行以项目根目录为根目录。

| 内容 | 相对路径 |
| --- | --- |
| SQLite 数据库 | `data/sitetask.db` |
| 设置 | `config/settings.json` |
| 损坏设置备份 | `config/settings.corrupt-*.json` |
| 轮转日志 | `logs/sitetask.log` |

请备份 `data/sitetask.db` 以保留任务。应用运行时不要手工编辑数据库。

## 测试

```bat
scripts\test.bat
```

或者：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

请以当前提交的测试运行结果为准；历史验收报告不代表后续提交已经通过验证。AI 测试不发送真实收费请求。

## 构建

```bat
scripts\build.bat --check
scripts\build.bat
```

输出：`dist\SiteTaskAI\SiteTaskAI.exe`。构建模式为 PyInstaller `onedir`，不能只复制 EXE 而丢弃 `_internal`。

清理构建目录：

```bat
scripts\clean.bat
```

## 隐私说明

- 任务、设置和日志默认只保存在本机程序目录。
- 本版本没有用户账户、云同步、在线数据库或后台服务器。
- 只有启用 AI 且本地解析置信度不足时，原始自然语言输入才会发送给配置的 OpenAI 服务。
- API Key 由 Windows Credential Manager/keyring 保存，不保存在普通配置文件中。
- 日志默认不记录完整任务文本，并对常见 API Key 格式脱敏；异常诊断省略原始错误文本、源代码行和完整本机路径。
- 本地队列请求、回执、归档及拒绝文件可能含完整任务和邮件链接，与数据库同样需要保密。
- 用户应根据所在组织的隐私和项目保密要求决定是否启用 AI。

## 已知限制

- 仅支持 Windows 10/11 x64。
- 构建未进行数字签名。
- `onedir` 发行版必须完整保留 `_internal`。
- AI 解析需要网络、有效 API Key、模型权限，并可能产生 API 费用。
- 一次自然语言输入只提取一个任务。
- 通知要求应用保持运行，全天任务没有具体时间，因此不会发送定时通知。
- 系统长时间睡眠并错过通知宽限期时，旧提醒不会无限补发。
- 暂停通知是当前运行会话状态，重启后恢复为设置中的通知状态。
- 本地解析覆盖常用中英文表达，但非常规或高度歧义文本仍需人工确认。

## 未实施功能

本版本没有 Gmail/Outlook 自动读取、邮件自动生成任务、会议录音或转录、云同步、多人协作、用户登录、手机或 Web App、团队权限、自动发邮件、附件、看板、甘特图、项目成本、后台服务器、WorkerW 桌面嵌入、多个 AI Provider，以及一次输入多个任务。

## 后续规划建议

后续版本可在不改变三天显示规则的前提下考虑：数据库导入导出、更完善的睡眠恢复通知、应用内更新与代码签名、可配置本地解析词典，以及经明确授权的外部集成。V3 功能应继续按独立阶段设计和测试。

详细结果见 `TEST_REPORT.md`、`BUILD_REPORT.md` 和 `FINAL_ACCEPTANCE_REPORT.md`。

## 本机授权任务队列（2026-10-06）

现支持已授权流程在应用运行中通过本地JSON文件队列新增/更新关联任务。应用自身执行保存；外部CLI只写队列文件，不写运行中的SQLite。不开放端口或网络访问，默认未配置时关闭。协议、严格字段限制、去重/完成保护、冲突策略、读取当前状态及启停方式见[QUEUE_API.md](QUEUE_API.md)。
