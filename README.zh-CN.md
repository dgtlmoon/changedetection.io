# changedetection.io 中文说明

**语言：** [English](README.md) | [简体中文](README.zh-CN.md)

changedetection.io 是一个开源、可自托管的网站变化监控与通知服务。它会按设定的时间间隔抓取网页或接口内容，保存历史快照，在内容发生变化时展示差异，并通过邮件、Discord、Slack、Telegram、Webhook 等渠道发送提醒。

简单来说，它适合解决这类问题：**“这个网页什么时候发生了我关心的变化？”**

![changedetection.io 监控界面](https://raw.githubusercontent.com/dgtlmoon/changedetection.io/master/docs/screenshot.png)

## 项目用途

- 监控商品价格、降价幅度、缺货与重新到货状态。
- 跟踪政府公告、法规、合同、招标信息和其他重要文档的更新。
- 关注软件版本、安全公告、招聘页面、房源和活动信息。
- 检测 PDF 文档的文本、文件大小或校验值变化。
- 监控 JSON API 返回结果，并通过 JSONPath 或 jq 提取目标字段。
- 监控网站源代码或关键页面，辅助发现异常篡改。
- 在特定关键词出现、消失或满足数值条件时触发通知。
- 将变化结果通过 Webhook 或 REST API 接入自动化工作流。

## 工作方式

```text
添加监控网址
    ↓
定时抓取页面或 API
    ↓
使用 CSS、XPath、JSONPath、jq 等规则提取目标内容
    ↓
与上一份快照比较
    ↓
应用关键词、数值条件或 AI 意图规则
    ↓
记录差异并发送通知
```

## 核心功能

- **清晰的差异对比**：可以按单词、行或字符查看内容变化。
- **精确选择监控范围**：支持 CSS Selector、XPath 1/2、JSONPath、jq、正则表达式以及可视化选择器。
- **两类抓取方式**：普通 HTTP 抓取速度快；连接 Playwright/Chrome 后可处理 JavaScript 动态页面。
- **浏览器步骤**：在检测前自动点击按钮、填写表单、接受 Cookie、登录或执行搜索。
- **价格与补货监控**：提取商品元数据，设置价格上限、下限或变化百分比，并查看历史趋势。
- **条件触发**：可按关键词、文本或数值条件过滤无关变化。
- **灵活调度**：设置检查间隔、星期、时间段和时区。
- **丰富的通知渠道**：基于 [Apprise](https://github.com/caronc/apprise)，支持邮件、Discord、Slack、Telegram、Microsoft Teams、Office 365、自定义 API 等大量服务。
- **代理与请求定制**：可为监控项配置代理、请求头、`GET`、`POST` 等请求方式。
- **REST API**：通过 API 管理监控项、标签、通知等资源，并提供 OpenAPI 规范。
- **多架构支持**：支持常见 Linux 环境以及 Raspberry Pi、ARMv6、ARMv7、ARM64。

## AI / LLM 功能

项目支持通过 [LiteLLM](https://github.com/BerriAI/litellm) 连接 OpenAI、Gemini、Anthropic、Ollama、vLLM、LM Studio 及其他兼容 OpenAI API 的服务，可用于：

- 根据自然语言意图判断一次变化是否值得通知，例如“仅在价格低于 50 美元时提醒”。
- 将原始差异整理成简短的自然语言摘要。
- 过滤导航栏、页脚等无关变化，减少误报。

使用云端模型时，页面差异和提取文本会发送给所选的第三方 AI 服务，并可能产生 API 费用。需要完全本地处理时，可以配置 Ollama、vLLM、LM Studio 等本地端点。LLM 输出可能存在遗漏或错误，不应被视为完整、准确的事实来源。

## Windows GitHub 仓库监控 EXE

本分支新增了独立的 Windows 桌面工具 **GitHubMonitor.exe**，用于监控一个或多个 GitHub 仓库。添加仓库 URL 后，可以分别选择：

- README；
- 配置文件（支持自定义 Glob 匹配规则）；
- Releases（附件可按 Windows、macOS、Linux、其他/通用版本筛选下载）；
- Issues；
- Pull requests；
- Security alerts（Dependabot、Code scanning、Secret scanning）；
- Discussions。

第一次检查会建立基线并自动测试下载：保存当前 README 和全部匹配配置文件，同时保存最近更新的一条 Release、Issue、Pull request、Discussion 以及每类最新安全告警。Release 的说明和元数据始终保存；附件仅下载用户勾选的 Windows、macOS、Linux、其他/通用版本，源码 ZIP 使用独立开关。以后检测到新 Release 或实际内容变化时，程序会弹窗提醒并下载更新。GitHub Token 即 GitHub Personal Access Token（PAT）；单击“Token 设置…”后只需粘贴令牌，程序会自动验证，并可使用当前 Windows 用户的 DPAPI 加密保存，不以明文写入配置文件。

使用、权限、下载目录结构和自行构建 EXE 的说明见：[Windows GitHub 仓库监控器](docs/GITHUB_MONITOR_WINDOWS.md)。

## 快速开始

### 方式一：Docker Compose（推荐）

```bash
git clone https://github.com/Given-Dream/changedetection.io.git
cd changedetection.io
docker compose up -d
```

启动后访问：<http://127.0.0.1:5000>

默认配置会把数据保存在 Docker 命名卷 `changedetection-data` 中。停止并重新创建容器不会自动删除该数据卷。

### 方式二：Docker 单容器

```bash
docker run -d \
  --restart always \
  -p "127.0.0.1:5000:5000" \
  -v changedetection-data:/datastore \
  --name changedetection.io \
  dgtlmoon/changedetection.io
```

也可以使用镜像：`ghcr.io/dgtlmoon/changedetection.io`。

### 方式三：Python 包

当前项目要求 Python 3.11 或更高版本。

```bash
pip3 install changedetection.io
changedetection.io -d /path/to/empty/data/dir -p 5000
```

随后访问：<http://127.0.0.1:5000>

Windows 安装说明请参阅[官方 Wiki](https://github.com/dgtlmoon/changedetection.io/wiki/Microsoft-Windows)。

## JavaScript 页面与可视化选择器

默认 HTTP 抓取器适合普通网页。若目标网站依赖 JavaScript、需要登录或需要交互，应连接 Playwright/Chrome 抓取器。

仓库中的 [`docker-compose.yml`](docker-compose.yml) 已提供相关配置示例。启用时需要同时取消以下内容的注释：

1. 主服务中的 `PLAYWRIGHT_DRIVER_URL` 环境变量。
2. `browser-sockpuppet-chrome` 服务。
3. 相应的 `depends_on` 配置。

详细配置参见 [Playwright 内容抓取器说明](https://github.com/dgtlmoon/changedetection.io/wiki/Playwright-content-fetcher)。

## 基本使用流程

1. 打开 Web 界面并添加需要监控的 URL。
2. 设置检查间隔，必要时指定工作日、时间段和时区。
3. 使用可视化选择器、CSS、XPath、JSONPath 或 jq 缩小监控范围。
4. 配置忽略文本、关键词触发、数值阈值或其他条件。
5. 在监控项的编辑页面中填写一个或多个通知 URL。
6. 保存后等待定时检查，也可以手动执行一次检查。
7. 发生变化后，在历史记录中查看旧版本、新版本和差异内容。

## 通知配置

通知 URL 在监控项的编辑页面中配置。以下为格式示例，请替换为自己的凭据：

```text
discord://webhook_id/webhook_token
mailto://user:password@example.com?to=receiver@example.com
msteams://TokenA/TokenB/TokenC/
json://example.com/custom-api
```

完整渠道与参数请参考 [Apprise 通知服务列表](https://github.com/caronc/apprise#popular-notification-services)。通知标题和正文还可以使用 Jinja2 模板进行定制。

请勿把真实密码、令牌或 Webhook 地址提交到 Git 仓库。

## JSON API 监控

可以使用 JSONPath 或 jq 从 API 响应中提取、筛选和重组数据。例如：

```text
json:$.price
jq:.products[] | select(.stock > 0) | {name, price}
```

`jq` 更适合包含逻辑判断、数组变换或复杂结构重组的场景。项目也可以从 HTML 的 `<script type="application/ld+json">` 中提取嵌入式 JSON。

更多示例参见 [JSON 选择器与过滤器说明](https://github.com/dgtlmoon/changedetection.io/wiki/JSON-Selector-Filter-help)。

## REST API

- [交互式 API 文档](https://changedetection.io/docs/api_v1/index.html)
- [OpenAPI 规范](docs/api-spec.yaml)

启用 API 密钥后，请按照 API 文档通过 `x-api-key` 请求头传递密钥。

## 更新

### Docker Compose

```bash
docker compose pull
docker compose up -d
```

### Docker 单容器

先拉取新镜像，再使用原来的端口、数据卷和环境变量重新创建容器。只要继续挂载同一个 `changedetection-data:/datastore` 数据卷，监控配置和历史数据就会保留。

## 常用文档

- [项目 Wiki](https://github.com/dgtlmoon/changedetection.io/wiki)
- [代理配置](https://github.com/dgtlmoon/changedetection.io/wiki/Proxy-configuration)
- [反向代理配置](https://github.com/dgtlmoon/changedetection.io/wiki/Running-changedetection.io-behind-a-reverse-proxy)
- [不同浏览器视口尺寸](https://github.com/dgtlmoon/sockpuppetbrowser#setting-viewport-size)
- [Chrome 扩展](https://chromewebstore.google.com/detail/changedetectionio-website/kefcfmgmlhmankjmnbijimhofdjekbop)
- [上游项目](https://github.com/dgtlmoon/changedetection.io)

## 安全与合规提示

- 监控网站前，请确认相关行为符合目标网站的服务条款、`robots.txt`、访问策略和适用法律。
- 默认 Compose 配置仅监听 `127.0.0.1:5000`。若要通过公网访问，建议使用 HTTPS 反向代理、访问控制和强密码，不要直接暴露无保护的服务端口。
- 使用浏览器步骤保存登录信息时，应妥善保护数据目录及备份。
- 使用第三方代理、通知平台或 AI 服务时，请评估页面内容中个人信息、商业数据和访问凭据的传输风险。
- 通知和 AI 生成的内容可能不完整；重要变化应回到原始网页核实。

## 开源许可与项目关系

本项目采用 [Apache License 2.0](LICENSE) 开源许可。

此仓库是 [dgtlmoon/changedetection.io](https://github.com/dgtlmoon/changedetection.io) 的分支。功能、镜像、官方 Wiki 和主要文档由上游项目维护。本中文 README 用于帮助中文用户快速了解和部署项目；如中文说明与当前代码或英文文档不一致，请以代码、[英文 README](README.md) 和上游官方文档为准。

## 致谢

感谢 changedetection.io 的作者与所有贡献者，以及 Apprise、Playwright、LiteLLM 等开源项目。
