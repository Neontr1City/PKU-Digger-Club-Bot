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
2. 同数据库运行 `uv run python -m cricket worker` 后，自动查询、纠错并补全发行、封面及链接。两首各有一个可信平台链接即可自动就绪，无需逐组审批。
3. `/admin` 的提名详情显示状态、修正对照和证据。只有找不到可信匹配的项需人工处理；缺少一个平台或封面默认接受。查询失败会间隔 15 分钟重试，最多 3 次，也可重新查找。罕见未匹配项可用艺人／厂牌官网、Bandcamp、Discogs 补证。
4. 就绪后指定日期与组数并创建；默认每天一组，0 表示暂停，首版上限 20 组。遇到待处理队首会停住，可明确跳过，不偷偷重排。旧待确认条目可在详情页点自动查找，既有就绪／历史曲目不自动改写。
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

自动提名需要常驻 `uv run python -m cricket worker`：每分钟处理一组并执行日常任务。`uv run python -m cricket resolve` 只处理一组后退出。演示时两个命令均需前缀 `DEMO_MODE=1 DATABASE=data/demo.sqlite3`，与网页保持同库；仅开网页不会执行补全。自动排期可继续关闭，不影响提名处理；将来微信模块再消费消息。规则详见 [自动提名处理标准](nomination-pipeline.md)。

结果图需要中文字体：macOS 使用系统字体；Linux 安装 `fonts-noto-cjk` 或设置 `RESULT_FONT`。每张最多四组，长文字按实际宽度换行，画布随内容伸长。结果图读取已结算曲目信息，用红色突出胜者、紫色表示平局；零票不产生胜者。

结果图中的封面来自已核对的 artwork 链接，仅下载 HTTPS 的 Apple（`*.mzstatic.com`）与网易云（`*.music.126.net`）CDN，不跟随重定向。首次生成会下载并缓存到 `OUTPUT_DIR/artwork/`（默认 `output/artwork/`），后续直接复用；该目录不提交 Git。下载超时、格式不支持、体积超过 5 MB、尺寸超过 4096px 或来源不在名单时，显示标有“封面暂缺”的唱片示意，票数和文字照常生成。网页封面展示仍使用原始链接。更换链接会自动使用新的缓存条目。

## Azure 部署前准备

已提供 Dockerfile、固定依赖与 Compose 草案；**本机没有完成容器构建或云端验证**。正式部署前选择 Azure 区域／规格，查看预计计算、磁盘与公网 IP 总费用，再创建资源；现有 学生赠金的额度与到期时间以账户为准，不视为永久免费。

部署时需要的材料仅为用户在 Azure 控制台核准的资源及访问方式，以及可用的公网 HTTPS 主机名方案。无需在聊天发送 Azure 密码或密钥。域名及免费主机名的可用性另行比较，当前没有购买域名。

云端参考步骤（尚未执行）：

1. 创建选定 Linux VM，上传代码；在服务器重新生成 `.env.local`，不要上传本地演示库。设置 `PUBLIC_BASE_URL=https://最终主机名`，`DEMO_MODE=0`。
2. 安装 Docker Compose 后，在项目根目录执行 `docker compose -f deploy/compose.yaml up -d --build app`。应用仅监听 VM 的 `127.0.0.1:8000`；数据库使用持久目录，不在容器镜像内。
3. 配置 DNS 与主机上的 HTTPS 反向代理。`deploy/Caddyfile.example` 是待替换域名的模板；服务监听本机端口不代表已配置 HTTPS。确认 80/443、SSH 访问范围；不公开数据库、8000 或微信控制接口。
4. 在手机微信内验证 HTTPS、提名、投票、听歌链接跳转；这里不能用本机桌面浏览器测试替代。
5. 启动 `docker compose -f deploy/compose.yaml --profile schedule up -d worker` 处理提名；确认北京时间与规则后，再在后台开启自动排期。这仍不发送微信。
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
