# 首版运行与部署手册

更新：2026-09-27。当前仅在本机验证；没有部署 Azure，也没有接入微信发送。

## 本地启动

需要 Python 3.11+ 与 uv。项目锁定的运行环境为 Python 3.12。

```sh
uv sync --locked --python 3.12
uv run python -m cricket init
uv run python -m cricket serve
```

打开 http://127.0.0.1:5057 。`init` 只在配置不存在时生成 `.env.local`，管理密码在其中的 `ADMIN_PASSWORD`，不要发到聊天或 Git。首次实际数据库为空；自动排期默认关闭。

隔离演示（示例票数，适合看界面）：

```sh
DEMO_MODE=1 DATABASE=data/demo.sqlite3 uv run python -m cricket demo
DEMO_MODE=1 DATABASE=data/demo.sqlite3 uv run python -m cricket serve
```

演示填充命令只运行一次，已有演示数据时会拒绝重复填充。演示轮次从生成时刻附近开始，翌日截止；再次运行服务器不会重置时段。正式库与演示库必须保持不同路径。

## 管理员操作

1. 群友在 `/nominate` 填昵称、两首歌曲的艺人和曲名，以及可选备注；不填写听歌链接。
2. `/admin` 登录后按序核对：查曲库候选，打开对应发行来源，确认艺人、曲名、版本、专辑，再填写来源地址。Apple 目录可选中国大陆／美国；MusicBrainz 支持分别检索艺人与曲名。需要时交叉查看艺人／厂牌官网、Bandcamp、Discogs；这些后备源目前由管理员手动打开。
3. 网易云／Apple 分享地址、封面图片及其发行来源均需确认。找不到时明确留空；缺少听歌链接必须勾选允许缺失。工具不会猜测歌曲 ID，也不会把搜索排序最高的翻唱自动发布。
4. 审核后变为就绪。指定日期与组数，点击创建；默认每天一组，0 表示暂停，首版上限 20 组。遇到未审核队首会停住，可明确跳过再创建，不会偷偷重排。
5. 查看轮次预览。未来轮次在开始时间前不向访客开放，已创建轮次的歌曲不再修改。截止前访客不见票数，可改票或撤回；每组互相独立。

时间按北京时间，初始 18:00 **仅为可修改的演示默认值**。修改切换时间只影响后来创建的轮次；上线前确认时间并避免已创建轮次重叠。平局提示双方平局，零票不选胜者；这些是待确认的规则草案。

## 每日入口和导出

```sh
uv run python -m cricket tick
uv run python -m cricket backup
uv run python -m cricket export
```

`tick` 会结算过期轮次；只有管理员开启自动排期且到切换时间后，才创建当日活动，并按「昨日结果 PNG→祝贺→今日曲目和链接」准备消息。重复执行不重复消费队列。未能准备当天曲目时保留原因，排期完成后可再执行。**prepared 只表示准备内容，绝不表示已发微信。** 停机后恢复只处理当前日期，不自动补发错过的各天活动。

`backup` 使用 SQLite 备份接口写入 `output/backups/`。`export` 将提名与证据、每轮汇总、已结算结果 PNG 写入 `output/export-时间/`，不导出浏览器投票标识。原始数据库仍包含昵称与投票标识，妥善保存；两个目录都已忽略 Git。

可选常驻 `uv run python -m cricket worker` 每分钟调用一次任务。当前本机只启动网页，未启动 worker，也未开启自动排期；将来微信发送模块再消费准备好的消息并记录发送状态。

结果图需要中文字体：macOS 使用系统字体；Linux 安装 `fonts-noto-cjk` 或设置 `RESULT_FONT`。每张最多四组，长文字按实际宽度换行。

## Azure 部署前准备

已提供 Dockerfile、固定依赖与 Compose 草案；**本机没有完成容器构建或云端验证**。正式部署前选择 Azure 区域／规格，查看预计计算、磁盘与公网 IP 总费用，再创建资源；现有 学生赠金的额度与到期时间以账户为准，不视为永久免费。

部署时需要的材料仅为用户在 Azure 控制台核准的资源及访问方式，以及可用的公网 HTTPS 主机名方案。无需在聊天发送 Azure 密码或密钥。域名及免费主机名的可用性另行比较，当前没有购买域名。

云端参考步骤（尚未执行）：

1. 创建选定 Linux VM，上传代码；在服务器重新生成 `.env.local`，不要上传本地演示库。设置 `PUBLIC_BASE_URL=https://最终主机名`，`DEMO_MODE=0`。
2. 安装 Docker Compose 后，在项目根目录执行 `docker compose -f deploy/compose.yaml up -d --build app`。应用仅监听 VM 的 `127.0.0.1:8000`；数据库使用持久目录，不在容器镜像内。
3. 配置 DNS 与主机上的 HTTPS 反向代理。`deploy/Caddyfile.example` 是待替换域名的模板；服务监听本机端口不代表已配置 HTTPS。确认 80/443、SSH 访问范围；不公开数据库、8000 或微信控制接口。
4. 在手机微信内验证 HTTPS、提名、投票、听歌链接跳转；这里不能用本机桌面浏览器测试替代。
5. 确认北京时间与规则后，在后台开启自动排期，启动 `docker compose -f deploy/compose.yaml --profile schedule up -d worker`。这仍不发送微信。
6. 备份：`docker compose -f deploy/compose.yaml exec app python -m cricket backup`；定期保留一份主机以外的副本。恢复时停止 app/worker，将选定备份复制为 `data/cricket.sqlite3`，再启动；先另存现有库，不直接覆盖唯一副本。

不需要本地电脑保持开机；以上条件在云端完成后，网页和任务由 VM 运行。

## 开发验证

```sh
uv run ruff check .
uv run ruff format --check .
uv run djlint cricket/templates --check
uv run pytest -q
```

测试覆盖顺序排期、提名重试、投票变更／截止／分组、不可变历史、平局／零票、称呼规则、消息顺序、访问保护、来源校验及 PNG 分页。均为临时数据库与虚构昵称，不涉及真实群消息。

部署说明参考（查证 2026-09-27）：[Docker Compose profiles](https://docs.docker.com/compose/how-tos/profiles/)、[Caddy HTTPS 反向代理](https://caddyserver.com/docs/quick-starts/reverse-proxy)。这些是公开配置文档，不能替代本项目云端实际验证。

## 查看当前票数

登录 `/admin` 后，顶部“正在进行的投票”显示每组双方票数、比例、总票数和截止时间；点击“活动详情”可查看对应轮次与发布内容。页面可见时每 15 秒更新，也可点击“刷新票数”；不影响下方未提交的设置。关闭 JavaScript 时通过浏览器刷新查看最新票数。未开始或已截止的轮次不会列入实时面板；历史结果仍从“已安排的对决”进入。
