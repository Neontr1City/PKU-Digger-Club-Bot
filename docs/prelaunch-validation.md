# 上线前小样本验收

查证及执行日期：2026-09-27。范围是本地功能与真实曲库查询，不是规模测试，也不是云端或微信内验收。所有提名昵称、选票为虚构样本，未向群发送消息。

## 时间与定时任务

已按用户确认设置北京时间 **每天 12:00:00 发布，次日 11:59:00 截止**。例如 9 月 27 日的一轮从 9 月 27 日 12:00 开放，到 9 月 28 日 11:59 截止；11:59 起拒绝新票和改票，12:00 开放下一轮。

- 验证开始前拒绝、开始时开放、截止前最后一微秒允许、截止时拒绝；存储为 UTC，展示为北京时间。
- 跨月（9 月 30 日）和跨年（12 月 31 日）同样正确。11:59 结算后没有提前建立下一轮，12:00 按「昨日结果图→祝贺→今日投票」准备内容。
- 重复执行不重复消耗队列，保存新时间不改写既有轮次；后台拒绝会导致日轮次重叠的设置。
- 曲库查找改为单独线程，日常任务按整分钟运行。用阻塞的查找样本确认第二次日常任务仍能执行，且不重复领取查找任务。
- 本机演示库已备份并保存新设置；原有两轮示例时段保持原样。新数据库默认采用 12:00／11:59，旧数据库升级保留既有发布时间，可从后台修改。
- 自动排期仍关闭。上述仅验证内容准备；云主机、真实微信发送和系统休眠／停机时准点送达均未验证。

## 真实曲库与提名队列

以下为规则 .1 的基线验收（.2 补充见下一节）。先运行独立检索，再在隔离 SQLite 数据库提交 5 组提名，实际调用 `enrichment.process_next`，没有人工改写解析结果。共 **10 条输入（6 首不同的真实歌曲，加错字／重制写法及 2 条虚构输入）**：8 条正例找到正确歌曲和封面；2 条负例未被错配。4 组自动就绪，包含负例的 1 组保留待处理。

| 输入 | 自动采用 | 平台与结果 |
| --- | --- | --- |
| 万能青年旅店 — 秦皇岛 | 同名曲，平台专辑名「万能青年旅店 同名专辑」 | 网易云 386835，481 秒，封面成功 |
| 草东没有派对 — 山海 | 同名曲，丑奴儿 | 网易云 411314659，251 秒，封面成功 |
| Slint — Good Morning, Captian | Good Morning, Captain / Spiderland | Apple 295785340（459 秒）＋网易云 1304520482（461 秒，重制版），封面成功 |
| Black Country, New Road — Concore | Concorde / Ants From Up There | Apple 1586070262＋网易云 1916369849，均 364 秒，封面成功 |
| Ichiko Aoba — Parfum d’étoiles | Parfum D'étoiles / Windswept Adan | Apple 1714304939，173 秒，封面成功；保留平台大小写 |
| Deep Purpel — Aprli | Deep Purple — April / Deep Purple | 网易云 4021290，730 秒，重制标记不显示，封面成功 |
| 万能青牛旅店 — 秦皇岛 | 万能青年旅店 — 秦皇岛 | 中文艺人错字恢复，网易云链接与封面成功 |
| Slint — Good Morning, Captain (Remastered) | Good Morning, Captain / Spiderland | 双平台与封面成功，不要求确认重制版 |
| Slint — Good Morning, Captain (Live at Imaginary PKU 2099) | 未采用 | 保留待处理，没有拿普通录音代替虚构现场版 |
| 完全不存在的样本艺人 PKU 2099 — 这首歌不存在 9fce73 | 未采用 | 保留待处理，没有采纳搜索返回的无关热门歌曲 |

前 3 组又走通了创建投票、投票／改票、截止拒收、冻结结果及结果 PNG，实际得到 2:0、1:1、1:1，图片票数、胜负与 6 张封面一致。负例与后续正例未被排期操作改写。

独立核对依据（同日查阅，均为公开曲目信息）：

- 万能青年旅店：[Apple 秦皇岛发行页](https://music.apple.com/us/song/1538548884)，[MusicBrainz 专辑曲序与 8:01 时长](https://musicbrainz.org/release/b27ad74f-c8e5-4698-9d18-800539368ff8)。自动目录保留网易云原始专辑名称，不冒称已统一为首版名称。
- 草东没有派对：[LINE MUSIC 的山海／醜奴兒条目](https://music-tw.line.me/track/7143541010)，[Spotify 对应发行及 4:11 时长](https://open.spotify.com/track/0VUORVhLmsxKTSwg4P9CrB)。
- Slint：[乐队／Touch and Go 的 Spiderland](https://slint.bandcamp.com/album/spiderland)，第 6 首与 7:39 时长对应；网易云重制版差 2 秒，在已确认接受范围内。
- Black Country, New Road：[乐队／Ninja Tune 的 Ants From Up There](https://blackcountrynewroad.bandcamp.com/album/ants-from-up-there)，第 3 首 Concorde，标示 6:03；目录的 364 秒相差约 1 秒。
- Ichiko Aoba：[艺人 Windswept Adan](https://ichikoaoba.bandcamp.com/album/windswept-adan)，第 6 首 Parfum d'étoiles，标示 2:52；目录 173 秒相差约 1 秒。页面大小写与 Apple 元数据不同，不擅自改写平台原文。
- Deep Purple：[原有示例核验](demo-metadata.md)；这次再次从网易云搜索和详情确认 ID、时长、专辑及封面。

原始查询报告、来源 URL、修正记录、时间、缓存与隔离数据库保存在 Git 忽略目录 `output/prelaunch/`：`sample-0.json` 至 `sample-7.json` 为独立检索报告（已用 .2 重跑更新），`queue-1.json` 至 `queue-5.json` 为完整队列报告，`queue.sqlite3` 为样本库，`results.png` 为验收图片。这些本地产物不提交仓库。

### 已知边界

这不是曲库覆盖率统计。短中文曲名错字、艺人中英文别名、繁简差异尚不能全面恢复。实际 Apple 目录将万能青年旅店写为 Omnipotent Youth Society；网易云将青叶市子写为中文名。这类身份不能只靠曲名相同就强行合并；.1 基线保留一个可信平台链接，.2 已增加下文的有来源别名桥接。缺少证据时仍保留单平台，照常自动就绪。不能把未采用的链接称为「该平台不存在这首歌」。

本次 MusicBrainz 偶有请求失败，中国区 iTunes 搜索多次返回空结果；有可信单平台时不阻塞。Apple 正例使用实际返回的美区链接，未在真实用户账号中验证完整播放。公开网页检索和目录元数据能够确认发行信息，不能证明任意地区账号都可播放或歌曲就是某个特定母带。

## 日文名称与国区优先补充（规则 .2）

用户补充了汉字／假名／罗马音的对应需求，并确认 Apple Music 国区优先。实际 Apple API 证明：同一歌曲 ID `720743504` 在日区返回 `青葉市子 — いきのこり●ぼくら`，美区返回 `Ichiko Aoba — Ikinokori●Bokura`；国区 ID 查询也返回此条目。不会通过替换 URL 猜造地区。

| 实际输入 | 自动采用的国区条目 | 网易云 | 结果 |
| --- | --- | --- | --- |
| 青葉市子 — いきのこり●ぼくら | 720743504，青叶市子 — Ikinokori●Bokura | 27974805 | 双链接、封面成功 |
| あおばいちこ — いきのこり●ぼくら | 同上；保留 MusicBrainz 读音证据 | 27974805 | 双链接、封面成功 |
| Aoba Ichiko — Ikinokori●Bokura | 同上；保留姓名顺序别名证据 | 27974805 | 双链接、封面成功 |
| Ichiko Aoba — Parfum d’étoiles | 1714304939，青叶市子 — Parfum D'étoiles | 1499834114 | 双链接、封面成功 |
| 宇多田ヒカル — 光 | 1444573374，Utada — Hikari，默认接受重制版 | 1332238900 | 双链接、封面成功 |

这 5 条输入的真实结果全部采用国区；另将假名青叶市子与宇多田光组成一组真实提名任务，已自动就绪且两首都是国区链接。完整报告在 `output/prelaunch/japanese-0.json` 至 `japanese-4.json`、`japanese-queue.json`，隔离数据库为 `japanese.sqlite3`。后台实际渲染确认可查 Apple ID、名称对应和艺人读音来源。

- [青叶市子官网](https://ichikoaoba.com/ja/about/) 明确并列日文名与 ICHIKO AOBA；[MusicBrainz 艺人别名](https://musicbrainz.org/artist/fc3ae4dd-dcc5-4f99-a865-6bc1a5c9b705/aliases) 的 API 实际返回 `あおば いちこ`、`Ichiko Aoba`、`Aoba Ichiko`。
- Apple 已取得的真实国区链接：[Ikinokori●Bokura](https://music.apple.com/cn/album/ikinokori-bokura/720743229?i=720743504)、[Parfum D'étoiles](https://music.apple.com/cn/album/parfum-d%C3%A9toiles/1714304663?i=1714304939)、[Hikari](https://music.apple.com/cn/album/hikari-remastered-2018/1444573229?i=1444573374)。查询可返回不等于已验证用户账号完整播放。
- 单元回归另验证平／片假名与半角归一化、保留 は／ば／ぱ 区别；没有读音证据不会猜配，同名艺人冲突、不同歌曲 ID／时长和现场版本不被强行合并。跨平台缓存候选不会被本次别名关联污染。
- 国区链接优先与封面发行优先分开：若国区链接位于合集，仍可使用同录音正式专辑发行的封面，保存独立封面证据；有专门回归用例。
- 加入此能力后再次真实查询原 8 条独立检索样本：6 条正例仍成功，2 条虚构输入仍未错配。其中秦皇岛、Slint、Concorde 和 Parfum 均补到了真实国区链接；草东和 Deep Purple 仍接受可信的网易云单平台。详见 `regression-summary.jsonl`。

## 封面与页面

网页及结果图共用 `OUTPUT_DIR/artwork/`；数据库保留原始 URL 和发行来源。网页通过带签名的站内地址取图，仅允许既定 Apple／网易云 CDN、禁止跳转，不能当作任意 URL 代理。

- 已缓存封面在模拟外网失效时正常返回；未缓存且下载失败时返回「封面暂缺」占位，不缓存失败结果。
- 验证浏览器缓存响应及 ETag／304、无签名或非允许来源被拒绝，图片请求不创建投票身份 Cookie。
- 浏览器确认当前 4 张示例封面均来自站内 `/artwork/`，真实解码尺寸 600×600。桌面及 390px 手机尺寸无横向溢出，图片与原界面一致。
- 62 项自动测试、Ruff、模板格式与 diff 空白检查通过。测试入口：`uv run pytest -q`；时间边界在 `tests/test_activity.py`，封面在 `tests/test_results.py`，慢查询与定时隔离在 `tests/test_worker.py`。

下一阶段是 Azure 云端部署及手机微信内验证；微信自动发送仍须独立完成接入验证。

## Azure 部署验收（2026-09-27）

- 实际环境：East Asia，Ubuntu 24.04 x64，B2ats_v2，Docker／Compose。Gunicorn app、独立 worker、Caddy 三个容器启动，app healthcheck healthy。正式库 DEMO_MODE=0，初始 nominations／rounds／votes 均为 0，SQLite quick_check 为 ok。
- 公网：可信 HTTPS `/health` 返回 ok，`/today` 和 `/nominate` 返回正常页面；未登录 `/admin` 跳转登录页。用实际生产密码通过 HTTPS 登录、查看票数入口、保存 12:00／11:59／自动排期设置并退出，Secure 会话 cookie 有效。生产密码未输出到日志。
- 云端隔离临时库：通过 Flask 路由提交虚构昵称的一组 `Deep Purpel / Aprli` 与 `青葉市子 / いきのこり●ぼくら`，实际查询修正为 Deep Purple — April，以及青叶市子 — Ikinokori●Bokura，任务 complete。前者网易云 4021290，Apple 缺失可接受；后者网易云 27974805、Apple 国区 720743504，均缓存封面。
- 该临时组创建轮次，通过投票路由计入 1 票；次日北京时间 11:59:00 截止，结算胜者 Deep Purple，Linux 中文字体成功生成 1080×1474 PNG。临时数据库自动清理，未写入生产提名或票数。
- 重新发布并重建、重启 app／worker 后，生产库 quick_check 仍为 ok，12:00／11:59／automatic=1 设置保留；应用与外部 HTTPS 健康检查通过。
- SQLite 定时备份已手动执行成功，下次计划北京时间 12:10。备份当前仍在同一主机，未将其描述为异机灾备。
- 本轮本地 62 tests passed、Ruff、djlint 通过。本机内嵌浏览器访问正式 URL 超时，未据此宣称完成公网视觉验收；命令行 HTTPS 与服务器功能已验证。手机微信内的国内网络可达性、提名、投票与网易云／Apple Music 跳转待用户实际设备验证；未向微信群试发。

私有执行记录位于 `output/deploy/`（不入 Git）：runtime／cloud-smoke／public-verification／final-deploy，以及部署文件 SHA-256 manifest。

## 用户提供的历史提名抽样（2026-09-27）

用户提供一份 42 组旧提名 CSV，授权整理和抽样测试，不是正式队列导入。所有行保留原序号、配对与原文，拆分艺人／曲名；5 组（10 首）原文缺艺人，留空待核对。分栏不等于所有发行信息已核验。含昵称的整理结果、原始候选、来源、缓存和报告仅保存在 Git 忽略目录 `output/legacy-validation-20260927/`；不复制原表 IP／答题来源。测试库昵称替换为虚构样本，曲库只收到艺人和曲名。

抽取 12 组覆盖正反顺序、by／斜杠／无空格连字符、全角符号、缩写、typo、合作署名及冷门分段作品。保持已部署的规则 .2 不变，实际通过 nominate→process_next 执行：

- 首次仅分栏后 **8 组自动就绪**，3 组有未解决项，1 组缺艺人被表单数据校验拒绝。11 组实际检索 22 首，18 首自动匹配；其中 16 首双平台、17 首取得缓存封面、16 首使用 Apple 国区。成功的单首不意味着其整组已就绪。
- 缩写与来源别名、相邻拼写错误及全角标点有实际恢复；单平台或缺图项仍按用户规则接受。
- 两组漏匹配分别源于省略 feat. 客串署名、只填合作发行的一位艺人。依据实际平台与艺人发行资料补全测试输入后，2 组复测均自动就绪，**这两组不能算入首次自动成功数**。本次最终 10/12 组验证可用，不将有选择的小样本当作整体准确率。
- 保留未解决的分段作品：平台用 Side A／Side B 命名，而录音资料使用作品名；另一首有 Part 1／Part 2／Complete，不能任意选一段。缺艺人亦不凭作品知名度补填。
- 一组联合署名问题伴随 MusicBrainz 暂时失败被归为 error；保留网络与匹配两种原因，不把“未采用”说成“歌曲不存在”。
- 从已就绪样本取 4 组，在隔离库显式跳过未就绪项后创建轮次，逐组投虚构 1:0 票并结算，PNG 已目视检查长文字／真实封面／缺图占位。这个测试步骤不改变生产队首规则。CSV 回读核对全部 42 组顺序、配对、Unicode、原文与缺失值。

下一步应优先改进带来源的 feat.／合作署名识别，再评估分段作品的对应；不能简单移除所有括号、仅按主艺人包含关系通过，或降低相似度阈值。完整私有报告见该忽略目录的 `测试报告.md`、`results.json`、`curated-results.json`。本轮没有修改线上代码、线上数据或自动排期，也未发送微信群消息。


## 客串／合作署名修正复测（规则 .3）

按 D020 更新规则后，以历史 CSV 的原始分栏输入重新创建两组隔离提名，未使用上一轮手工补充的输入：

- The Dinosaur's Skin / Millions of years apart 与 Andr / 安：整组 complete。前者曲名现显示 Millions of Years Apart，MANDARK 移至艺人署名；Apple 国区 ID 1573166630，网易云缺失接受。
- Cocteau Twins / Sea, Swallow Me 与 Múm / We Have A Map Of The Piano：整组 complete，合作曲自动保留 Cocteau Twins & Harold Budd 完整署名，双平台链接通过。

四首均有 Apple 国区链接，三首双平台。这次两组属于**程序自动通过**，与 .2 的人工补输入复测分别保留。完整结果见忽略目录 `output/credit-validation-20260927/results.json`。新增署名、合作身份及错误版本回归后共 76 tests passed；不写入正式提名或改写历史结果。

规则 .3 已部署 Azure：部署前备份生产库，app／worker 两容器实际导入版本均为 2026-09-27.3，SQLite quick_check、12:00／11:59／automatic=1 与公网 HTTPS `/health` 均通过。未批量修改已有提名或历史轮次。

## 2026-09-28 · 线上测试提名与合作署名回归

- 云端第一组 Joni Mitchell 的 The Arrangement / The Circle Game 中，后者在规则 .3 被不同合作阵容阻塞。诊断只读取曲目和任务结果，不导出昵称。
- 规则 2026-09-28.1：单人优先、明确多人输入必须全部匹配、候选合作阵容不单独阻塞；先选有来源的较早正式专辑录音，再选对应平台链接。93 项测试通过。
- 本地真实查询 The Circle Game 选择 Ladies of the Canyon，国区 Apple 1492312810 与网易云 18822069；反向多人输入 Harold Budd / Cocteau Twins 的 Sea, Swallow Me 也取得合作发行和双链接。
- 备份后部署并通过正常任务队列重跑第一组，云端验证 ready / complete，两首原始输入保留、两首双平台；第二组保持 ready。未创建额外测试提名、未试发微信群。
- 公网健康检查与 SQLite 完整性检查通过。具体查询报告、发布日志和云端验证在忽略目录 output/circle-game-20260928/。
