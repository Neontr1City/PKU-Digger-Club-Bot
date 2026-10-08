# 首版运行与部署手册

更新：2026-09-28。网站已部署至 Azure 香港区域；同机 Linux 微信已接入自动发送；用户已确认测试群完整流程成功。

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

结果图输出宽 864 像素、256 色压缩 PNG，冻结结果缓存于 `OUTPUT_DIR/results/`，网页和微信共用，重复打开无需再次绘图。结果图需要中文字体：macOS 使用系统字体；Linux 安装 `fonts-noto-cjk` 或设置 `RESULT_FONT`。每张最多四组，长文字按实际宽度换行，画布随内容伸长。结果图读取已结算曲目信息，用红色突出胜者、紫色表示平局；零票不产生胜者。

结果图中的封面来自已核对的 artwork 链接，仅下载 HTTPS 的 Apple（`*.mzstatic.com`）与网易云（`*.music.126.net`）CDN，不跟随重定向。首次生成会下载并缓存到 `OUTPUT_DIR/artwork/`（默认 `output/artwork/`），后续直接复用；该目录不提交 Git。下载超时、格式不支持、体积超过 5 MB、尺寸超过 4096px 或来源不在名单时，显示标有“封面暂缺”的唱片示意，票数和文字照常生成。网页与结果图共用这个缓存；网页经带签名的站内封面地址读取，另存 480px WebP 派生图，浏览器不直接请求平台 CDN；原始 600px 缓存保留给结果图。已缓存图片可在外部断网时复用，未缓存且下载失败则返回缺图占位，60 秒后访问可重试。同一进程对同图合并同时发生的下载，最多两个外部封面下载，其余请求先显示缺图占位，避免占满网页线程。原始 URL 与发行证据仍保存在数据库。更换链接会自动使用新的缓存条目。

## Azure 正式部署

已部署至 [正式站点](https://pkudigger.eastasia.cloudapp.azure.com)，提名 `/nominate`、管理 `/admin`。正式数据库为空起步，不导入本地演示；网站自动排期已开启，北京时间 12:00 发布、次日 11:59:00 截止。空队列不创建空活动。微信发送已在指定测试群验证，尚未切换正式运营群。

实际资源（2026-09-27）：资源组 `pku-digger-club`，VM `pku-digger-web`，East Asia（香港），Ubuntu 24.04 x64，`Standard_B2ats_v2`（2 vCPU／1 GiB），32 GiB Standard SSD、静态 Standard IPv4。保留学生订阅支出上限，没有升级付费订阅。计算免费权益与磁盘／IP 费用须分开，见 [云端费用记录](cloud-hosting.md)。

服务位于 `/opt/pku-digger-club-bot`：Docker Compose 启动 app、worker、Caddy。Caddy 自动签发／续期 HTTPS；仅 80/443 对公网开放，8000 只绑定本机。证书持久化到 Docker volume；SQLite、封面和备份位于主机 `data/`、`output/`。服务器无需本地电脑常驻。

### 首次部署与更新

2026-10-08 用户已授权今后功能更新在完成验证后自动部署至现有 VM。按下述流程先备份、上传和重建，再核对实际代码版本及服务健康；无需逐次申请部署许可。遇到后续明确的暂停或先报告要求时，遵循用户最新指示。

当前 Azure DNS 标签为 `pkudigger`；2026-09-27 已从原长标签切换，旧地址失效。未来若再次改名，先备份数据库与 `.env.local`，更新公网 IP 的 DNS 标签，再显式修改 `.env.local` 中 PUBLIC_BASE_URL 并重建 app／worker／Caddy 容器。`start.sh` 不会静默覆盖已有地址。新域名会使用新的浏览器身份与登录 Cookie，宜在投票轮次之间切换。

普通 Ubuntu 24.04 上首次执行 `sudo bash deploy/bootstrap-ubuntu.sh` 安装 Docker／Compose 与 1 GiB swap，再上传发布包并执行：

```sh
cd /opt/pku-digger-club-bot
sudo bash deploy/start.sh https://你的主机名
```

`start.sh` 首次生成服务器专用随机密码／会话密钥，`.env.local` 权限为 600；更新时保留原配置、数据和证书，不重置管理密码。正式实例管理密码另存于操作者本机忽略目录 `output/deploy/admin-access.txt`。不要把该文件提交或粘贴进日志。

本次本机代理不能直连 SSH，已通过 **Azure VM Run Command** 完成部署，无需打开公网 SSH。使用已认证的 Azure CLI（本机优先 `az login`，在浏览器完成登录），在本地项目根目录：

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

### 手动更换管理员密码

正式站点使用服务器 `/opt/pku-digger-club-bot/.env.local` 的 `ADMIN_PASSWORD`，修改本地开发配置不会影响云端。可在本机忽略文件 `output/deploy/new-admin-password.txt` 中填写一行新密码，通过已认证的维护流程同步；不要将密码粘贴到聊天、命令行参数或公共日志。

更新时只替换 `ADMIN_PASSWORD`，保留会话密钥及其他配置；私有配置权限保持 600。随后执行 `docker compose --env-file .env.local -f deploy/compose.yaml --profile schedule up -d --no-deps --no-build app worker`，重新创建服务以加载环境变量（单独 `restart` 不会更新容器环境）。微信客户端独立运行，无需重启。最后核对 `/health`，使用新浏览器会话验证新密码登录，并更新私有的 `output/deploy/admin-access.txt` 记录。已有管理员登录会话不会因这次配置修改立即失效，最长保留到原来的八小时截止时间。

2026-09-28 查证：若 Azure 返回 `AADSTS530035`，安全默认策略可能拦截设备代码登录。改用普通 `az login` 浏览器登录并完成所要求的验证；保持安全默认策略开启，不反复尝试相同设备代码。参见 [微软安全默认策略](https://learn.microsoft.com/en-us/entra/fundamentals/security-defaults)。

### 小内存主机的压缩缓存

2026-09-29 故障修复启用 `deploy/pku-digger-zswap.service`，在内核支持时启动 zswap，压缩池上限为物理内存的 20%，按需占用；保留原来的 1 GiB 磁盘 swap 作为后备。它不等于增加物理内存，也不承诺消除所有资源压力。未扩容 VM 或购买新服务。维护时可读取 `/sys/module/zswap/parameters/enabled`、`max_pool_percent` 与 `/proc/pressure/{memory,io}` 验证。

新主机按需安装：`sudo install -m 0644 deploy/pku-digger-zswap.service /etc/systemd/system/`，然后 `sudo systemctl daemon-reload`、`sudo systemctl enable --now pku-digger-zswap.service`。回退时禁用该服务并向 `enabled` 写入 `0`，已有压缩页会随换入逐步释放；不要为回退强行执行 `swapoff`。内核行为依据 [Linux zswap 文档](https://www.kernel.org/doc/html/v6.8/admin-guide/mm/zswap.html)，查证于 2026-09-29。

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

历史对决入口位于页面底部“最近的对决”；只有一轮时也显示日期。点击日期可查看已结算票数、胜者与结果图，结束后不能再改票。

## 管理员邮件提醒

可选 QQ 邮箱通知需要 worker 常驻，默认未启用。将 QQ 邮箱、SMTP 授权码与启用开关存入服务器私有配置，详见 [配置及通知规则](admin-notifications.md)。`python -m cricket mail-test` 会实际发送一封测试邮件，只在完成账号配置并需要验证收信时运行；不接收公开网页提供的任意收件地址。

## 云端微信客户端验证

原 Azure VM 已运行最小 Linux 微信容器，并在服务器启用 `WECHAT_DESKTOP_ENABLED=1`。登录 `/admin` 后点击「打开云端微信」，用机器人账号扫码；入口复用网站管理员会话与 HTTPS。容器的构建、限制、登录目录、停止方法和会话失效边界见 [运行说明](../deploy/wechat/README.md)。默认示例配置仍关闭此入口。

已实现指定群的结果图、祝贺、曲目／链接自动发送，以及掉线邮件。微信容器与网站独立，启用发送阶段使用 `unless-stopped` 随主机恢复；微信可能仍需手机重新确认，登录失效会暂停发送并提醒。唯一联调群为「PKU Digger Bot测试」，不要在正式运营群试发。

### 手机与云端微信会话

最新验收：用户在华为 Pura 70 Pro 的应用分身保留机器人登录、原微信使用主号，云端发送的第二条测试消息已由主号收到，分身仍登录。不要用同一个微信内部的“切换账号”代替这两个独立应用。容器当前限制为 512 MiB 内存／1024 MiB 内存加 swap／1024 个进程与线程；原 256 线程上限已证实过紧。暂保留诊断镜像会话，后续维护时恢复普通镜像，不立刻中断当前登录。

自动发送使用服务器原生 UTF-8 剪贴板，文字粘贴后逐字核对；不经过 noVNC 的旧剪贴板通道。人工使用 noVNC 粘贴中文／表情仍须检查输入框。用户已实测手机内部切号会退出云端，应用分身并用可以保留当前登录；不要清理登录目录排障。

发送进度、邮件通知、异常恢复和配置见 [微信推送与掉线提醒](wechat-delivery.md)。正式运营群尚未启用。当前正在使用的登录会话没有为部署而重启；已把发送程序和启动脚本同步进容器，常规镜像也包含相同源码。后续按正常 Compose 重建时会恢复普通镜像，可能需要用户再次手机确认。

## 小规模并发与故障预案

用户已授权按约 200 人群体进行有限验证；重复提交、截止、备份、微信／邮件／曲库故障和网站恢复步骤见 [robustness.md](robustness.md)。使用隔离数据，不对正式投票灌入样本。

## 正式启用（2026-10-07）

已按用户要求切换至「今天你滚了吗（pku版）」，北京时间 2026-10-08 12:00 起运行。提名链接：https://pkudigger.eastasia.cloudapp.azure.com/nominate。`settings.launch_day` 与发送端 `send_not_before` 阻止提前消费队列或推送，后台显示起始日；默认一组、次日 11:59 截止，空队列不创建空投票。正式群禁止试发，原测试记录不改目标，首日不发布测试期结果。当前待提名队列为空，需先有自动就绪提名。

群名参考排除群人数，见 [发送说明](wechat-delivery.md)。变更正式目标或界面布局前先停止 worker，保留备份并重新核验；不得仅修改群名后将旧消息重新定向发送。
