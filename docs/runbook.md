# 首版运行与部署手册

更新：2026-09-27。网站已部署至 Azure 香港区域；未接入微信发送。

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

用户已确认北京时间每日 **12:00 发布、次日 11:59:00 截止**，截止的这一分钟不再接收投票。后台分别设置发布时间与次日截止，截止不得晚于下一次发布。设置只影响后来创建的轮次；旧数据库初始化会保留已有发布时间，升级时在后台保存新时间。本机演示库已更新设置并备份，原有两轮示例的起止时间未改动。平局提示双方平局，零票不选胜者；这些是待确认的规则草案。

## 每日入口和导出

```sh
uv run python -m cricket tick
uv run python -m cricket backup
uv run python -m cricket export
```

worker 的结算／排期按整分钟唤醒，曲库检索在独立线程中每次处理一组，各自使用数据库连接，慢检索不拖延定时循环。系统停机或操作系统调度仍可能造成延迟，尚不承诺微信消息准点送达。`tick` 会结算过期轮次；只有管理员开启自动排期且到切换时间后，才创建当日活动，并按「昨日结果 PNG→祝贺→今日曲目和链接」准备消息。重复执行不重复消费队列。未能准备当天曲目时保留原因，排期完成后可再执行。**prepared 只表示准备内容，绝不表示已发微信。** 停机后恢复只处理当前日期，不自动补发错过的各天活动。

`backup` 使用 SQLite 备份接口写入 `output/backups/`。`export` 将提名与证据、每轮汇总、已结算结果 PNG 写入 `output/export-时间/`，不导出浏览器投票标识。原始数据库仍包含昵称与投票标识，妥善保存；两个目录都已忽略 Git。

自动提名需要常驻 `uv run python -m cricket worker`：每分钟处理一组并执行日常任务。`uv run python -m cricket resolve` 只处理一组后退出。演示时两个命令均需前缀 `DEMO_MODE=1 DATABASE=data/demo.sqlite3`，与网页保持同库；仅开网页不会执行补全。自动排期可继续关闭，不影响提名处理；将来微信模块再消费消息。规则详见 [自动提名处理标准](nomination-pipeline.md)。

结果图需要中文字体：macOS 使用系统字体；Linux 安装 `fonts-noto-cjk` 或设置 `RESULT_FONT`。每张最多四组，长文字按实际宽度换行，画布随内容伸长。结果图读取已结算曲目信息，用红色突出胜者、紫色表示平局；零票不产生胜者。

结果图中的封面来自已核对的 artwork 链接，仅下载 HTTPS 的 Apple（`*.mzstatic.com`）与网易云（`*.music.126.net`）CDN，不跟随重定向。首次生成会下载并缓存到 `OUTPUT_DIR/artwork/`（默认 `output/artwork/`），后续直接复用；该目录不提交 Git。下载超时、格式不支持、体积超过 5 MB、尺寸超过 4096px 或来源不在名单时，显示标有“封面暂缺”的唱片示意，票数和文字照常生成。网页与结果图共用这个缓存；网页经带签名的站内封面地址读取，浏览器不直接请求平台 CDN。已缓存图片可在外部断网时复用，未缓存且下载失败则返回缺图占位，下次访问可重试。原始 URL 与发行证据仍保存在数据库。更换链接会自动使用新的缓存条目。

## Azure 正式部署

已部署至 [正式站点](https://pkudigger.eastasia.cloudapp.azure.com)，提名 `/nominate`、管理 `/admin`。正式数据库为空起步，不导入本地演示；网站自动排期已开启，北京时间 12:00 发布、次日 11:59:00 截止。空队列不创建空活动。微信发送尚未接入。

实际资源（2026-09-27）：资源组 `pku-digger-club`，VM `pku-digger-web`，East Asia（香港），Ubuntu 24.04 x64，`Standard_B2ats_v2`（2 vCPU／1 GiB），32 GiB Standard SSD、静态 Standard IPv4。保留学生订阅支出上限，没有升级付费订阅。计算免费权益与磁盘／IP 费用须分开，见 [云端费用记录](cloud-hosting.md)。

服务位于 `/opt/pku-digger-club-bot`：Docker Compose 启动 app、worker、Caddy。Caddy 自动签发／续期 HTTPS；仅 80/443 对公网开放，8000 只绑定本机。证书持久化到 Docker volume；SQLite、封面和备份位于主机 `data/`、`output/`。服务器无需本地电脑常驻。

### 首次部署与更新

当前 Azure DNS 标签为 `pkudigger`；2026-09-27 已从原长标签切换，旧地址失效。未来若再次改名，先备份数据库与 `.env.local`，更新公网 IP 的 DNS 标签，再显式修改 `.env.local` 中 PUBLIC_BASE_URL 并重建 app／worker／Caddy 容器。`start.sh` 不会静默覆盖已有地址。新域名会使用新的浏览器身份与登录 Cookie，宜在投票轮次之间切换。

普通 Ubuntu 24.04 上首次执行 `sudo bash deploy/bootstrap-ubuntu.sh` 安装 Docker／Compose 与 1 GiB swap，再上传发布包并执行：

```sh
cd /opt/pku-digger-club-bot
sudo bash deploy/start.sh https://你的主机名
```

`start.sh` 首次生成服务器专用随机密码／会话密钥，`.env.local` 权限为 600；更新时保留原配置、数据和证书，不重置管理密码。正式实例管理密码另存于操作者本机忽略目录 `output/deploy/admin-access.txt`。不要把该文件提交或粘贴进日志。

本次本机代理不能直连 SSH，已通过 **Azure VM Run Command** 完成部署，无需打开公网 SSH。使用已认证的 Azure CLI（`az login --use-device-code`），在本地项目根目录：

```sh
python3 deploy/package.py --base-url https://pkudigger.eastasia.cloudapp.azure.com
az vm run-command invoke -g pku-digger-club -n pku-digger-web \
  --command-id RunShellScript --scripts @output/deploy/upload-release.sh \
  --query 'value[].message' -o tsv
```

发布包只包括应用、运行依赖与部署脚本；包含当前未提交修改，旁附 SHA-256 清单，不包含 `.env.local`、数据库或本地 output。Run Command 返回成功仅表示命令被执行，必须检查输出 `DEPLOY_OK` 和 `/health`，不能只看 Azure CLI 的退出码。此上传方式适合当前小型源码包，文件明显变大后再改用存储上传；不要在命令中打印密钥。每次只执行一个 Run Command。

服务器内日常命令（可写进本机忽略目录的 shell 文件后通过 Run Command `--scripts @文件` 执行）：

```sh
cd /opt/pku-digger-club-bot
docker compose --env-file .env.local -f deploy/compose.yaml --profile schedule --profile https ps
docker compose --env-file .env.local -f deploy/compose.yaml logs --tail 30 worker
docker compose --env-file .env.local -f deploy/compose.yaml exec -T app python -m cricket backup
```

### 备份与恢复

`pku-digger-backup.timer` 每日北京时间 **12:10** 运行 SQLite 一致性备份，存入 `output/backups/`；错过任务时下次开机补执行。`systemctl list-timers pku-digger-backup.timer` 查看下次执行时间。这是同一 VM 的备份，不能代替异机副本；有正式数据后定期另存到操作者设备。

恢复时先停止 app／worker，另存当前数据库，再将选定备份复制到 `data/cricket.sqlite3`，随后启动服务。不要覆盖唯一副本，不要复制正在写入的原始 SQLite 文件当作备份。Caddy 证书 volume 和服务器 `.env.local` 需保留。

公网 HTTPS 和云端功能验收见 [验收记录](prelaunch-validation.md)。手机微信内提名、投票及听歌应用跳转仍需真人手机验证；桌面浏览器不能替代。

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
