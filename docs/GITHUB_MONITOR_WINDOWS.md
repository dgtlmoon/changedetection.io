# Windows GitHub 仓库监控器

`GitHubMonitor.exe` 是本仓库附带的独立 Windows 桌面程序。它通过 GitHub API 比较仓库内容，不依赖 changedetection.io Web 服务，也不需要先启动 Docker。

## 功能

添加一个或多个 `https://github.com/owner/repository` 地址后，可以独立选择以下监控项：

| 监控项 | 判定内容 | 变化后保存的内容 |
| --- | --- | --- |
| README | 文件内容 SHA-256 与 Git Blob SHA | README 原文件、元数据 JSON |
| 配置文件 | 匹配文件的路径、Git Blob SHA、大小 | 新增/修改文件、增删改清单 JSON |
| Releases | 名称、Tag、正文、状态、目标分支、附件清单 | Release JSON/Markdown、所选平台附件、源码 ZIP |
| Issues | 标题、正文、状态、标签、负责人、评论数等 | Issue JSON/Markdown、最近 100 条评论 |
| Pull requests | 标题、正文、状态、分支 SHA、审阅人等 | PR JSON/Markdown、完整 diff、最近 100 条会话/审阅评论和审阅记录 |
| Security alerts | Dependabot、Code scanning、Secret scanning 告警对象 | 每条新增、更新或已解决告警的 JSON |
| Discussions | 标题、正文、答案、投票和最近评论 | Discussion JSON/Markdown（含评论） |

程序会先对有意义的字段做规范化再计算指纹，因此 GitHub API 返回顺序改变不会触发提醒。第一次成功检查会建立基线并执行有界的测试下载：README 下载当前文件，配置文件下载全部当前匹配项，Releases、Issues、Pull requests 和 Discussions 各下载最近更新的一条，Security alerts 下载每个可访问类型的最新一条。Release 首次下载和后续更新均遵循同一附件版本筛选。初始内容不会被误报为新变化；首次下载失败时不会写入该项基线，下一轮会重试。某一监控项因权限不足而失败时，其他项目仍可继续检查；失败项目的旧基线会保留，避免将“无权读取”误判为“全部删除”。

TLS 临时中断、连接重置以及 HTTP 408、429、500、502、503、504 会进行最多 3 次指数退避重试。重试后仍失败时，只记录本轮警告并保留旧基线，下一轮会继续检查。

## 使用方法

1. 运行 `GitHubMonitor.exe`。
2. 输入 GitHub 仓库 URL。
3. 选择下载目录和检查间隔。
4. 勾选要监控的内容。监控配置文件时，可逐行填写 Glob 规则。
5. 如需监控 Discussions、Security alerts、私有仓库或提高 API 限额，单击“Token 设置…”。弹窗中只需粘贴 GitHub Personal Access Token（PAT），无需填写用户名或密码；程序会自动验证、按设置加密保存，并让运行中的监控自动采用该令牌。弹窗还提供 GitHub 创建令牌页面、显示或隐藏、清除令牌等控件。
6. 按需选择是否下载 Release 附件和源码 ZIP；下载附件时，可勾选 Windows、macOS、Linux、其他/通用中的一个或多个版本。默认全部勾选以兼容旧配置，例如只需要 Windows 安装包时仅保留 Windows。
7. 单击“保存仓库”。新仓库会自动启动首次测试、建立基线并下载各勾选项的最新内容，此后按设定间隔检查。

“启动监控并立即检查所选”合并了启动和手动检查：监控停止时会先启动调度器，随后保存当前表单设置并检查所选仓库；监控已运行时则直接保存并检查。刚刚修改的监控内容、匹配规则、检查间隔和下载选项都会用于本轮检查。

程序必须保持运行，才能定时检查和弹窗。当前版本不安装 Windows 服务，也不自动加入开机启动项。

## GitHub 令牌与权限

公开仓库的 README、配置文件、Releases、Issues 和 Pull requests 通常可在不填写令牌时读取，但未认证请求的 API 限额更低。以下情况需要令牌：

- 私有仓库；
- Discussions（使用 GitHub GraphQL API）；
- Dependabot、Code scanning、Secret scanning 安全告警；
- 希望使用更高的已认证 API 限额。

建议使用 fine-grained personal access token，只授权需要监控的目标仓库，并只授予相应的只读权限：Contents、Issues、Pull requests、Discussions、Dependabot alerts、Code scanning alerts 和 Secret scanning alerts。安全告警还必须已在目标仓库中启用，并且令牌所属用户具备读取权限。

Token 设置窗口中的“验证成功后使用 Windows DPAPI 自动安全保存”默认开启。令牌验证成功后会通过 Windows DPAPI 绑定到当前 Windows 用户并自动保存，同时更新正在运行的调度器；程序日志不会输出令牌。取消勾选后，配置文件中不保留令牌，只在本次程序运行期间使用。

状态栏显示的是本轮观察到的最低 API 剩余额度。如果任一请求收到限流响应，本轮状态会明确显示“本轮已限流”，不会继续用其他成功请求的余额掩盖该错误。

## 下载目录

每个仓库使用独立目录，命名为 `owner__repository`：

```text
选择的目录/
└── owner__repository/
    ├── README/<检测时间>/
    ├── configs/<检测时间>/
    ├── releases/<tag>/<检测时间>/
    ├── issues/<编号>/<检测时间>/
    ├── pulls/<编号>/<检测时间>/
    ├── security/<告警类型>/<告警编号>/
    └── discussions/<编号>/<检测时间>/
```

应用配置、监控基线和事件日志默认保存在 `%APPDATA%\GitHubMonitor`。删除一个监控设置不会删除已经下载的文件。

## 构建 EXE

要求：Windows、Python 3.10 或更高版本、PyInstaller 6.22.1 或更高版本。

```powershell
python -m pip install "pyinstaller>=6.22.1,<7"
powershell -ExecutionPolicy Bypass -File .\build_github_monitor.ps1
```

如果默认 `python` 的 Tcl/Tk 安装不完整，可以显式指定另一个已安装 PyInstaller 且能运行 Tkinter 的 Python：

```powershell
powershell -ExecutionPolicy Bypass -File .\build_github_monitor.ps1 -Python "C:\path\to\python.exe"
```

构建脚本会先真实初始化一次 Tkinter，检查 PyInstaller 的安全最低版本，并在 Conda 环境下固定使用同一环境的 Tcl/Tk DLL。生成 EXE 后还会自动执行内部自检和完整界面启动冒烟测试；任一检查失败都会终止构建，避免交付无法打开或使用已知不安全 bootloader 的 EXE。

生成文件：

```text
artifacts\GitHubMonitor.exe
```

构建前可运行测试和启动自检：

```powershell
python -m unittest discover -s github_monitor_desktop\tests -v
python github_monitor.py --self-test
```

EXE 是单文件、无控制台窗口的便携程序，不会修改系统服务或注册表。运行时，PyInstaller 会把内部文件临时解压到当前用户的 `%LOCALAPPDATA%\GitHubMonitor\Runtime`，正常退出后自动清理本次 `_MEI...` 子目录。
自行构建的 EXE 未进行商业代码签名，Windows SmartScreen 可能在首次运行时显示来源未知提示；如需在组织内分发，应使用组织自己的代码签名证书完成签名。

## 已知边界

- REST 列表接口每次读取最近 100 条记录；对 Issues 和 Pull requests，程序忽略仅因记录滑出这个窗口产生的“删除”，以避免误报。
- Discussions 保存 API 返回的最近 100 条讨论及每条讨论最近 100 条评论。
- Release 附件平台按文件名和扩展名识别；无法明确判断平台的压缩包、校验文件和通用附件归入“其他/通用”。Release 说明和元数据不受附件筛选影响，源码 ZIP 由独立开关控制。
- Release 附件可能很大，会占用下载目录空间。
- 仓库删除、转为私有、令牌撤销或 API 限流会显示为检查警告，不会自动清空此前基线。
- 弹窗只在程序运行时显示；历史事件同时追加到 `%APPDATA%\GitHubMonitor\events.jsonl`。

## 数据与安全说明

- API 请求只发往 `https://api.github.com`。Release 二进制内容通过 GitHub API 资产地址发起，跟随 GitHub 的 HTTPS 存储重定向时会移除 Authorization 请求头，令牌不会被转发到下载域名。
- 下载的仓库内容可能包含密钥、内部配置或安全告警细节，请为目标文件夹设置合适的 Windows 访问权限。
- 请遵守 GitHub 服务条款、目标仓库许可及组织安全策略。
