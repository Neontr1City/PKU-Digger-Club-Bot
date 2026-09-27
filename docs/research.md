# 技术调研与来源

最新决定（D008）：提名与投票完全自建，从空队列开始，不做复杂防刷。下文问卷星接口研究仅作历史参考，不再是开发前置条件；现行步骤见 [开发计划](development-plan.md)。

调研日期：2026-09-27。下文区分「公开文档已证实」「方案判断」「需要真实账号验证」。未调用用户的付费接口，未登录问卷星，未对真实群发送消息。

最新方向：用户已确认日常运行不依赖本地电脑（D006）。下文桌面优先建议属于早期调研，现改为优先核查云端协议接入与 [免费云资源](cloud-hosting.md)，不要求用户电脑常驻。

## 1. 微信接入：先区分群类型

**结论：本次没有找到可供个人开发者免费调用、直接定时向现有普通微信群发送文字和图片的官方开放接口。**这不是对未来能力的绝对断言；在取得官方可用接口证据前，不能承诺「普通微信群＋无人值守＋官方认可」。

腾讯云官方文档明确写明：企业微信外部群暂不支持其群机器人配置。因此企业微信 webhook 不能作为本项目现有微信群的直接接入方案。[腾讯官方说明](https://cloud.tencent.com/document/product/248/50413)

| 路线 | 现有普通微信群 | 自动发送程度 | 费用与维护 | 本项目判断 |
| --- | --- | --- | --- | --- |
| A. 自动准备＋管理员在微信转发 | 保留原群 | 最后发送由人完成 | 本地程序可不增加服务费；需每日人工发送 | 用户已定为自动路线遇到实质困难后的退路 |
| B. 桌面微信界面自动操作 | 可能保留，需实机验证 | 可以尝试定时点选发送 | 依赖登录、电脑唤醒、窗口和客户端版本；免费工具不代表零维护 | 属于非官方自动化，不承诺平台认可或账号安全 |
| C. Wechaty／协议或 Hook 类接入 | 取决于底层适配器 | 能力取决于具体实现和账号 | 可能需要服务 token／费用，适配器可能失效 | 只有用户明确优先无人值守后才继续评估 |
| D. 企业微信内部群机器人 | 需要改变群形态与成员使用方式 | 官方接口支持消息推送 | 引入企业微信组织和群迁移成本 | 不适合默认要求 200 多位群友迁移 |

Wechaty 是第三方框架；其官方项目文档介绍的 Puppet Service 需要服务 token。这是 Wechaty 自身的技术说明，不是腾讯对个人微信群机器人的授权。不能从框架开源推导出底层接入免费可用。[Wechaty 文档](https://wechaty.js.org/zh/docs/puppet-providers/service)

公众号、小程序、微信客服和腾讯云 IM 也不能只因名称里有「微信／群／机器人」就当成个人微信群发送接口。若用户选择其中任何方向，先用对应产品官方文档核验目标会话范围，再决定是否改变现有使用流程。

企业微信开发站的 [群机器人说明](https://developer.work.weixin.qq.com/document/path/91770) 与 [企业群发接口](https://developer.work.weixin.qq.com/document/path/96366) 在本次工具访问中未能加载，浏览器补查也超时；不把转载页面当作对这些接口最新行为的充分验证。核心群类型结论采用上方可读的腾讯官方产品文档。

## 2. 问卷星：优先验证官方接口，不先入为主判定只能付费

查到了两类并存的官方说明：

- [API 总览](https://www.wjx.cn/help/help.aspx?h=1&helpid=333) 标注所列 API 仅向旗舰版提供。
- [ApiKey 使用说明](https://www.wjx.cn/help/help.aspx?catid=140) 提供后台自行生成 Key 的入口，并说明首次生成时默认开启常用问卷／答卷接口，实际权限沿用账号配置。
- [官方开源工具包](https://github.com/wjxcom/wjx-ai-kit) 提供 TypeScript SDK、CLI 和 MCP，列出创建问卷、读取答卷和报告等能力。

**不能据此断言免费账号一定能用，也不能断言所有接口一律付费。**下一步核验用户账户中读取提名、创建草稿、发布／停止回收、读取统计这几项是否可用且无新增费用；SDK 开源不等于服务接口免费。

建议的验证顺序：

1. 用户登录后台，确认账号版本与「用户信息 → ApiKey」入口是否存在。
2. 如果允许生成 Key，由用户在本机保存；先只读列出自己问卷、读取指定提名表的字段与少量脱敏样本。
3. 逐项记录权限与返回结果；不要拿「查询问卷成功」代替「创建／发布／统计都可用」。
4. 选定路线后，单独创建测试草稿：两组对决、封面、每首两个外链；预览通过后才用测试投票验证截止与统计，不改现有活动。

### 投票页能否容纳封面与听歌链接

问卷星的编辑器文档支持图片与超链接，投票入门文档支持选项图片、说明以及隐藏当前票数。因此保留问卷星值得先试，不必为了封面马上换平台。[编辑框说明](https://www.wjx.cn/help/help.aspx?helpid=435)、[投票入门](https://www.wjx.cn/help/help.aspx?catid=65)

推荐每组放两张歌曲资料卡，再放一题 A／B 单选；外链放在清楚的听歌入口，避免点选项时误触跳转。当天多组放在同一份新问卷，历史问卷保留，不每日改写同一份已有答卷的问卷。

注意问卷星「选项详情页」要求有且只有一道投票单选／多选，不能把它作为同日多组的必需能力。多组版直接在问卷主体展示资料。[选项详情页条件](https://www.wjx.cn/help/help.aspx?helpid=528)

尚需实测：当前账号能否使用相应富文本、API 能否保留这些内容、从微信点外链后能否方便返回继续投票。展示链接不等于能在微信内直接唤起音乐 App。

### 备选路线

| 方案 | 每日工作 | 优点 | 代价／待验证 |
| --- | --- | --- | --- |
| 问卷星官方 API | 自动读取提名、创建投票、截止、取统计 | 沿用群友习惯、无需自建投票服务 | 免费权限尚未确认 |
| 问卷星导入导出 | 定期导出提名，人工创建／复制当日投票，导入最终票数 | 可先完成校曲、排期、文案与结果图 | 每日仍有操作；实际账号导出权益待核实 |
| 保留问卷星提名＋自建投票页 | 提名通过 API 或导出导入；投票由程序管理 | 更容易自定义听歌卡片、计票和结果 | 需一个群友可访问的服务；自建投票不会自动解决问卷星提名读取 |
| 提名与投票都自建 | 两端都自动化 | 数据统一、可减少问卷星依赖 | 改变现有提名入口，超出默认范围，须用户选择 |

自建候选可考虑 Cloudflare Workers＋D1 的免费计划。官方当前列出 Workers 免费每日 100,000 请求，D1 也有免费额度；对本群活动的预估用量足够，但不能承诺中国大陆微信访问效果。[Workers 费用](https://developers.cloudflare.com/workers/platform/pricing/)、[D1 费用](https://developers.cloudflare.com/d1/platform/pricing/)

这是备选，不是已定部署：先由群友在日常网络、微信内打开试用页验证可达性；若不合适，使用已有可用主机，或保留问卷星。localhost 或仅有静态页面不能独立完成群友投票与可信计票。暂不购买域名或服务器。

匿名自建投票可用随机浏览器标识＋数据库唯一约束限制同浏览器重复提交，但无法严格保证一人一票、仅群成员投票；昵称和 IP 都不是可靠的个人身份。要更强约束需要另选身份方案，不能偷偷增加微信登录、短信收费或实名要求。

## 3. 音乐信息：证据优先级与检索渠道

目标分为三个：确认作品／录音身份、确认正式发行署名与专辑、找到当前可用的平台收听链接。不能拿搜索第一页或播放量最高的版本同时替代这三项。

| 来源 | 用途 | 访问与限制 |
| --- | --- | --- |
| 艺人／厂牌官网、官方 Bandcamp 页面 | 小众作品、正式曲目表、特别大小写、原始版本的主要证据 | 按具体艺人查官方发布页，人工确认页面身份 |
| MusicBrainz | 结构化艺人、recording、release、release group、ISRC 与别名匹配 | 非商业读取免费、通常不需 Key；最多每秒一次请求并带有效 User-Agent |
| Apple Music 正式歌曲／专辑页 | 发行署名、曲目、专辑和地区听歌链接 | 页面可公开查找；地区可用性需另外核实 |
| iTunes Search API | 无开发者 token 的低成本候选搜索 | 是 iTunes 目录而非完整 Apple Music 目录，不能当作国区 Apple Music 全量入口 |
| Discogs | 实体版本、曲目表、年份与封面差异的补充核对 | 本次开发文档返回 403；API 权限与使用条件未核验，首版只列为人工补充来源 |
| 网易云官方歌曲／专辑页 | 网易云歌曲链接与实际可听版本 | 本次未找到可据以承诺的免费通用官方搜索 API；优先提交者分享链接与人工搜索 |
| Cover Art Archive | 根据 MusicBrainz 具体发行查专辑封面 | 按 release／release group 查图，核对是否正面封面与对应版本 |

依据：[MusicBrainz API](https://musicbrainz.org/doc/MusicBrainz_API)、[免费与认证说明](https://musicbrainz.org/doc/MusicBrainz_API/FAQ)、[iTunes 搜索文档](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/Searching.html)、[Cover Art Archive API](https://musicbrainz.org/doc/Cover_Art_Archive/API)。

Bandcamp 公开开发 API 面向厂牌和商品履约等账户操作，不能当作免费全站曲库搜索 API；本项目用艺人／厂牌公开发行页核对小众音乐。[Bandcamp API](https://bandcamp.com/developer)

Apple Music 正式 API 需要开发者 token 与 Developer Program 身份，首版没有必要为歌曲链接新增这条依赖。[Apple 官方认证说明](https://developer.apple.com/documentation/applemusicapi/generating-developer-tokens)

### 匹配流程（拟开发）

1. 保留原始输入；解码 HTML 实体、规范 Unicode 与空白，生成搜索候选，不直接覆盖正式显示文本。
2. 若有提交者分享链接，先识别其艺人、专辑和具体版本；否则根据艺人＋曲名搜索 MusicBrainz 与公开发行页。
3. 比对艺人身份、曲名、专辑、版本说明、时长与年份；有 ISRC 时辅助匹配，但不把 ISRC 当成跨平台绝对无误的唯一依据。
4. 优先用发行方曲目表确定署名和特殊大小写；至少再用一个来源核对版本。仅有一个可信来源时标记待人工确认，不编造第二条证据。
5. 为网易云与 Apple Music 分别保存实际歌曲链接、地区、核对日期；不能从一个平台 ID 猜另一个平台 ID。Apple 国区优先尝试；若只找到其他区，显示地区而非假称国区可听。
6. 展示原始值 → 建议值、来源与版本差异；有歧义时管理员确认。正式名字不一律转标题大小写，也不删除 live／remix／重新录制等必要区别。
7. 确认后缓存记录，不每天对同一歌曲重新搜索。平台无此歌时保持缺失状态。

### 专辑封面选择

先确定提名针对的录音，再选择包含该录音的正式发行。未指定特殊版本时，优先原始正式专辑标准版，其次正式 EP，再次独立单曲；避免默认取精选集、合辑、现场专辑或豪华版替代原始专辑。若提名明确是现场版，就尊重对应正式现场发行，不强改成录音室版。

保存具体发行来源与封面引用，不只保存「搜到的一张图片」。Cover Art Archive 的 `front` 和 `approved` 可辅助筛选，但不是权利许可。iTunes 图片也有使用条件，不能因为接口返回了图片就默认可任意放进娱乐海报；首版结果图可不带封面，投票页封面按来源的使用条件处理，必要时使用获许可的素材或占位图。[Apple 素材条款](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/index.html)

### 用用户示例做的初步核对

下面只是发行身份核对样本，尚未完成每首两平台链接、地区可听性与封面复核，不能当作正式发布数据。

| 用户示例 | 初步证据 | 开发中需注意 |
| --- | --- | --- |
| Deep Purple - April | [乐队官网 1969 专辑页](https://deeppurple.com/products/deep-purple-1969)列出 April | 商品页标题含 1969，不应直接把商品标题当正式专辑名 |
| Pink Floyd - A Saucerful of Secrets | [乐队官网专辑页](https://www.pinkfloyd.com/albums/a-saucerful-of-secrets/) | 同名专辑与曲目须区分；各页 Of／of 的显示可能不同，保留采用来源 |
| The Smiths - There Is A Light That Never Goes Out | [Apple Music 正式歌曲页](https://music.apple.com/us/song/800157892)显示 There Is **a** Light That Never Goes Out，归于 The Queen Is Dead | 按该发行页采用小写 a；美国区链接不能证明中国区可听 |
| Mötley Crüe - Home Sweet Home | [厂牌 BMG 说明](https://www.bmg.com/news/moetley-cruee-team-up-with-dolly-parton-for-new-rendition-of-home-sweet-home)确认 1985 年 Theatre Of Pain 原版，并说明另有 Dolly Parton 合作新版本 | 保留 Mötley Crüe 变音符号，不能把新合作版本误配为原版 |

## 4. 推荐的验证次序

用户已确认优先自动发群、先保留问卷星。下一步根据设备选择自动发送候选，同时确认问卷星免费账号能力；再用少量真实提名验证曲目核对与富文本投票。只有这些验证通过后，才决定具体部署与依赖。

本次只完成公开资料调研；未声称完成 API 连接、客户端兼容、国区歌曲播放、统计准确性或实际发布验证。

## 5. 自动发送路线补充（根据用户选择继续调研）

**建议先做桌面界面自动化的最小验证，协议／Hook 作为后备候选。**本活动每天只发少量固定内容，不需要全天监听聊天或接入大模型。能否使用现有设备比框架功能多寡更重要。

| 候选 | 查证的能力与前提 | 下一步／局限 |
| --- | --- | --- |
| Windows：wxauto4 | 项目维护者文档提供免费包；列出 Windows、微信 4.1 及免费版最高兼容 4.1.8.107 | 这是调研当日的兼容说明；先核对实机版本，逐项确认文本／图片发送不依赖 Plus |
| Windows：pywechat／pyweixin | 基于 pywinauto 的 UI 自动化；当前 4.x 主要使用 pyweixin 模块 | 维护者报告部分账号的控件树不可见；先验证独立账号的界面可见性，再核对版本、锁屏行为 |
| macOS：原生辅助功能／界面操作 | 存在开源 Mac 发送脚本，演示文本和文件发送 | Mac 项目仅作为可行性线索；需要验证群定位、可预览的图片消息、前台与锁屏条件，不能承诺直接复用 |
| Wechaty | 跨语言框架＋Puppet 适配器 | 免费、可用的底层个人微信适配器尚未核定；不能只装 SDK 就认为能登录 |
| WeChatFerry | 项目列出文字／图片发送，代码包含注入模块；2026-09-27 查 GitHub API 已归档 | README 中适配记录包含微信 3.9.12.51；不为首版默认降级微信或引入 DLL 注入 |

一手资料：[wxauto 安装与兼容说明](https://docs.wxauto.org/docs/install.html)、[wxauto 原仓库](https://github.com/cluic/wxauto)、[pywechat 原仓库](https://github.com/Hello-Mr-Crab/pywechat)、[Mac 发送脚本原仓库](https://github.com/yunkai/macos-wechat-sender)、[WeChatFerry 原仓库](https://github.com/lich0821/WeChatFerry)。这些是第三方项目自己的资料，均不等于腾讯官方认可。

后续针对相似群机器人完成了专项调研，见 [项目比较](related-projects.md)。包括最接近定时运营的 WeChatGroupTask、娱乐机器人 wechat-robot-client、WeChatPadPro，以及 Gewechat 停更等变化；区分已公开的活动逻辑与未必免费／开源的微信服务端。

最低验证只需一次小规模功能演练：在用户指定测试会话中依次发送测试结果图、祝贺语、提名与链接；验证群定位与消息顺序、图片在手机上的显示、重新执行不重复发。不是压力测试或长期稳定性测试。

运行时要求目标会话唯一且可确认；登录失效、目标不明确或发送状态不确定时停止该次发送并留下待处理状态，不能盲目切到搜索首项或重复发送。只需读取判断发送是否成功的最小界面信息，不采集群聊历史。

设备未知前不承诺云端无人值守：Linux 云主机不能直接运行 Windows UI Automation；云 Windows 桌面、持久在线会话可能引入费用与额外维护。桌面方案是否允许锁屏、最小化和远程断连均以候选和实机验证结果为准。

## 6. 独立账号与官方机器人通道补查

用户明确期待像 QQ 群机器人一样，以独立账号存在于群中。这个群内形态可以作为项目目标：「独立普通微信账号＋程序控制」与「程序运行在本机／云端」是两个不同维度，不能因为讨论桌面自动化就默认用管理员本人身份发消息。

Wechaty 的登录文档说明通过微信扫码登录，Room API 提供群内发送文字和媒体的抽象接口；实际可用性仍取决于底层适配器。这说明存在普通账号驱动的群机器人技术形态，但不是某个免费适配器在当前客户端已经验证成功。[登录文档](https://wechaty.js.org/docs/api/wechaty)、[Room API](https://wechaty.js.org/docs/api/room)

本次补查也发现需要补充的官方路线：腾讯云产品文档描述了微信 ClawBot 扫码绑定并对话的入口；OpenClaw 项目文档将对应插件列为微信团队维护，并明确当前能力声明为私聊和媒体，未声明群聊支持。[腾讯云远程终端渠道](https://intl.cloud.tencent.com/zh/document/product/1254/81684)、[OpenClaw 微信通道文档](https://docs.openclaw.ai/channels/wechat)

因此不能笼统表述为「微信没有官方机器人」。准确结论仍是：尚未核实到满足本项目「加入现有普通微信群＋定时主动发送结果图片与消息」的官方通道。ClawBot 暂不作为已可用的群发送方案；未进行插件安装或实机验证。


## 2026-09-27 首版接口实测补充

本节是代码真实调用，与上文公开能力调研分开记录。请求使用公开歌曲名称，不含群友昵称或原始答卷。

- Apple iTunes Search：HTTP 调用成功并返回候选；`term=Deep Purple April`、US 区、25 个结果中，本次没有准确的 April 录音，返回同艺人其他歌曲及翻唱。程序保留候选供人工核对，不自动填写正确链接，也不能由此断言 Apple Music 没有这首歌。[官方搜索参数](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/Searching.html)。
- MusicBrainz recording 搜索：普通词串混入无关曲目；改为 `artist:"Deep Purple" AND recording:"April"` 后返回艺人 Deep Purple、曲名 April、1969-06-21 的候选，其中一个带 Deep Purple 专辑，另有合辑／版本。候选示例：[April recording](https://musicbrainz.org/recording/b6c9a560-b317-446c-9f89-7268a584eb6b)。仅表示找到可核对记录，尚未确认它与两听歌平台的具体音源一致。[API 文档](https://musicbrainz.org/doc/MusicBrainz_API)。
- 本地检索已分别保存艺人、曲名、专辑、来源、身份 ID、时长与日期候选；正式审核保存管理员选择的发行证据及确认时间。没有自动下载封面，没有调用网易云非官方接口。
- 没有新购曲库／API，没有申请 Apple 开发者会员。小众曲目人工后备渠道仍为艺人／厂牌官网、Bandcamp、Discogs，未将这些网站全部实现为自动抓取器。
