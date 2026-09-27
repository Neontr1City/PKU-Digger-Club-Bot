# PKU-Digger-Club-Bot

为 **PKU Digger Club**（微信群「今天你滚了吗（pku版）」）开发的小型音乐活动工具。

当前实现「每日斗蛐蛐」：群友提名两首歌，管理员核对后按序安排，每天投票选出更喜欢的一首。

**当前状态：网站可本地运行；尚未部署云端、尚未接入微信群自动发送。** 微信自动发送仍是后续开发方向，目前只生成待发送的文案和结果图。

## 功能

- **提名**：填写昵称、两首歌的艺人和曲名，以及可选备注，无需注册。听歌链接由管理员补充。
- **审核与排期**：保留原始提名与发行来源，按队列排期；支持每日多组、暂停和明确跳过待处理组。
- **投票**：每组独立选择，截止前可改票或撤回；普通页面截止后才显示结果。仅用浏览器标识防误重复，不做严格防刷。
- **听歌**：展示网易云／Apple Music 链接和专辑封面；提供 iTunes 与 MusicBrainz 候选检索，由管理员确认版本。重制母带版本默认接受，现场、混音和重新录制仍需区分。
- **活动管理**：密码登录；查看进行中的票数、比例和领先情况，每 15 秒局部更新，也可手动刷新。
- **结果与消息**：生成中文 PNG、祝贺和次日对决文案；支持平局、零票与同艺人胜者称呼。
- **数据维护**：SQLite 备份、提名与汇总结果导出、可选每日排期任务。

## 快速开始

需要 Python 3.11+ 与 [uv](https://docs.astral.sh/uv/)。推荐使用 Python 3.12，依赖版本由 `uv.lock` 固定。

```sh
git clone https://github.com/Neontr1City/PKU-Digger-Club-Bot.git
cd PKU-Digger-Club-Bot
uv sync --locked --python 3.12
uv run python -m cricket init
```

`init` 在本机生成随机密钥和管理员密码，保存到 `.env.local`；已有文件不会覆盖。管理员密码是其中的 `ADMIN_PASSWORD` 值。

### 查看隔离演示

```sh
DEMO_MODE=1 DATABASE=data/demo.sqlite3 uv run python -m cricket demo
DEMO_MODE=1 DATABASE=data/demo.sqlite3 uv run python -m cricket serve
```

打开 [本地首页](http://127.0.0.1:5057/today) 或 [管理后台](http://127.0.0.1:5057/admin)。演示使用虚构昵称与票数，含两组示例歌曲的封面和双平台链接。

`demo` 只需首次运行；已有数据时会拒绝重复填充。演示截止时间按首次生成时刻设置，重启不会重置。演示和实际活动必须使用不同数据库。

### 使用空队列

```sh
uv run python -m cricket serve
```

默认使用 `data/cricket.sqlite3`。先提交提名，再进入后台核对并创建投票。初始自动排期关闭，18:00 是待管理员确认的北京时间默认值。

以上环境变量写法适用于 macOS／Linux shell。Windows PowerShell 请使用 `$env:DEMO_MODE="1"`、`$env:DATABASE="data/demo.sqlite3"` 等对应写法。

## 配置与日常命令

配置示例见 [.env.example](.env.example)，实际配置存放于未跟踪的 `.env.local`。进程环境变量优先于该文件。

| 配置 | 用途 |
| --- | --- |
| `SECRET_KEY` | Flask 会话密钥，由 `init` 随机生成 |
| `ADMIN_PASSWORD` | 管理员密码，由 `init` 随机生成 |
| `DATABASE` | SQLite 路径，默认 `data/cricket.sqlite3` |
| `OUTPUT_DIR` | 备份和导出目录，默认 `output` |
| `PUBLIC_BASE_URL` | 群消息链接使用的站点地址；云端应配置为 HTTPS |
| `DEMO_MODE` | 仅隔离演示设为 `1`，正式活动设为 `0` |
| `RESULT_FONT` | 可选中文字体路径；Linux 可安装 `fonts-noto-cjk` |

```sh
uv run python -m cricket tick     # 执行一次结算与已启用的排期
uv run python -m cricket worker   # 可选，每分钟执行一次任务
uv run python -m cricket backup   # SQLite 一致性备份
uv run python -m cricket export   # 导出提名、汇总结果和已结算 PNG
```

这些命令均使用当前配置的数据库；操作演示库时需带上相同的环境变量。`prepared` 仅表示消息已准备，**不代表已发送微信**。

## 代码结构

Python + Flask 服务端模板 + SQLite + Pillow，无独立前端构建流程。

```text
cricket/
  __init__.py        应用配置、HTTP 路由与管理员认证
  __main__.py        唯一命令行入口、演示与数据维护
  service.py         提名、审核、排期、投票、结算和消息规则
  db.py / schema.sql 数据库连接与表结构
  music.py           公共曲库候选检索
  poster.py          结果 PNG 渲染
  demo_tracks.json   公开示例元数据及核验来源
  templates/        Jinja 页面与局部模板
  static/           CSS、JavaScript 和共用 SVG 标志
tests/              隔离数据库功能测试与曲库响应样本测试
deploy/             Docker Compose 和 HTTPS 代理配置示例
docs/               需求、决策、调研、开发记录与操作手册
```

## 开发与检查

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run djlint cricket/templates --check
uv run pytest -q
```

提交前如需整理格式：

```sh
uv run ruff format .
uv run djlint cricket/templates --reformat
```

修改依赖后运行 `uv lock`，并重新导出 Docker 使用的运行依赖：

```sh
uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file requirements.txt
```

测试使用临时数据库与虚构样本，不需要微信、Azure 或外部曲库账号。结果图测试需要中文字体。页面文案位置见 [文案与视觉修改指南](docs/editing-copy.md)。

日常修改同步维护受影响文档与 [开发日志](docs/changelog.md)。`.env.local`、数据库及其 journal/WAL 文件、原始提名、登录状态、备份和导出结果均不得提交；`.gitignore` 和 `.dockerignore` 已排除这些内容。

## 部署与待完成事项

提供 Dockerfile、Compose 和 Caddy 配置示例，部署步骤见 [运行与部署手册](docs/runbook.md)。当前尚未完成容器构建及云端验证；本地运行通过不等于已部署。

- 云端部署、HTTPS 和手机微信内跳转验证。
- 选择并验证向普通微信群自动发送的接入方式。
- 上线前确认发布时间、截止时间和活动规则。

本项目面向小型娱乐社群，优先免费、简单，不引入规模化服务或复杂防刷。

## 项目文档

- [需求与活动规则](docs/requirements.md) · [开发步骤与验收](docs/development-plan.md)
- [运行与部署手册](docs/runbook.md) · [文案与视觉修改指南](docs/editing-copy.md)
- [决策记录](docs/decisions.md) · [开发日志](docs/changelog.md)
- [示例曲目、链接与封面核验](docs/demo-metadata.md)
- [技术调研与来源](docs/research.md) · [相似机器人项目](docs/related-projects.md)
- [免费云服务器候选](docs/cloud-hosting.md) · [投票工具路线比较](docs/voting-options.md)

调研文档保留历史选型与查证日期；当前实现与决定以 README、需求和最新决策为准。示例歌曲与封面属于各自权利方，仓库只保存公开元数据和来源链接。
