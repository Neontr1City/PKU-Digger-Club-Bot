# 相似微信群机器人项目调研

查证日期：2026-09-27。依据项目原仓库、维护者文档、部分发送／调度源码及 GitHub 公共 API；没有安装、扫码登录或实机发送。下文的功能是项目声明或代码行为，不代表已在我们的账号上验证。

后续决定 D006：用户要求不依赖本地电脑，因此下文桌面方案仅保留作比较，当前优先云端接入。最新部署候选见 [免费云方案](cloud-hosting.md)。

## 结论

确实存在以独立普通微信账号参与群聊、执行定时任务的项目。它们通常将「活动逻辑」和「微信接入」分开：前者开源，不一定意味着后者也开源、免费或仍能登录。没有找到覆盖本项目问卷星提名、音乐版本核对、投票与结果图全流程的现成方案。

本次发现最接近活动运营的是 WeChatGroupTask 和 hp0912/wechat-robot-client；最值得做低成本设备验证的是 Windows UI 自动化；希望不占用本地桌面时，可以继续评估第三方协议服务，但当前没有证实一条同时免费、简单且获腾讯认可的普通群接入路线。推荐是候选顺序，不是用户已确认的选型。

## 1. 与群活动最接近的项目

| 项目 | 解决了什么 | 实际接入方式 | 对本项目的价值／缺口 |
| --- | --- | --- | --- |
| [WeChatGroupTask](https://github.com/oocsoo/WeChatGroupTask) | 群、素材、任务管理；按日／周／月或指定时间发文字、图片、文件 | Python 后台调用外部微信 SaaS，需要 ROBOT_ID、TOKEN 和服务地址 | 最接近每日发布；可借鉴排期与素材管理。外部服务当前费用、可用性未确认，仓库本身不是完整微信登录实现 |
| [wechat-robot-client](https://github.com/hp0912/wechat-robot-client) | 点歌、欢迎、群排名、群总结等；Pro 功能表列出定时文字／图片和管理员触发控制 | Go 应用＋管理后台＋iPad 协议服务；协议服务源码不公开，有 Docker 部署示例 | 接近用户设想的独立娱乐机器人。不能把 Pro 功能算进免费版；README 明确提示在线预览站当前不宜扫码，实际登录尚待验证 |
| [wechatgpt_pro](https://github.com/H4lo/wechatgpt_pro) | 群聊天和定时任务，配置指定群名 | Go＋[openwechat](https://github.com/eatmoreapple/openwechat)，扫码登录，可本地／Docker 运行 | 可参考小型群任务结构；最近推送在 2024 年，底层当前账号能否登录未知。openwechat 的桌面协议模式不等于桌面鼠标自动化 |
| [WeChatAPI-diange](https://github.com/WeChatAPIs/WeChatAPI-diange) | 群里提及机器人点歌，识别请求后返回音乐信息／链接 | WeChatSDK／第三方 WeChatAPI，另有 AI 调用 | 提供音乐群交互参考；不覆盖双曲投票，也没有证明正式发行版本校对、双平台链接和免费微信接入都已解决 |

### WeChatGroupTask 的源码启发

它把任务调度与发送服务分离，使用 APScheduler 和数据库记录群任务；我们也可以让活动逻辑只调用 `send_text`／`send_image`，以后更换接入方式不必改音乐和投票逻辑。[调度源码](https://github.com/oocsoo/WeChatGroupTask/blob/main/task_scheduler.py)

有一个不宜照搬的行为：发送函数取得 HTTP 响应后直接返回成功，没有核验业务结果；调度调用也未检查发送返回值就更新执行时间、停用一次性任务。我们的简单实现仍要区分「调用已返回」与「发送已确认」，不确定时保留待处理状态，避免漏发后误报成功或盲目重发。[发送源码](https://github.com/oocsoo/WeChatGroupTask/blob/main/wechat_service.py)、[调度源码](https://github.com/oocsoo/WeChatGroupTask/blob/main/task_scheduler.py)

这只是针对每日发群的基本正确性要求，不增加压力测试或企业运维系统。

## 2. 真正负责微信登录和发送的候选

| 候选 | 原理与设备 | 免费情况／当前边界 | 评估顺序 |
| --- | --- | --- | --- |
| [pywechat／pyweixin](https://github.com/Hello-Mr-Crab/pywechat) | Windows 10／11 的 UI Automation 操作已登录微信；Python | 文档提供本地安装，未列必须购买的服务 token；4.x 主要使用 pyweixin 模块，旧 pywechat 模块面向 3.9。许可与账号 UI 可见性仍需核对 | 有 Windows 时优先验证，先查能否识别界面 |
| [wxauto4](https://docs.wxauto.org/docs/install.html) | Windows 微信界面自动化 | 文档区分免费 wxauto4 与付费 wxautox4；免费兼容表列至 4.1.8.107，不能等同于所有更新版本；文本／文件接口有文档 | Windows 并列候选；不先购买 Plus，实测 PNG 是否以图片显示 |
| [macos-wechat-sender](https://github.com/yunkai/macos-wechat-sender) | Mac 上用键盘、鼠标和剪贴板搜索会话并发送；另有 OCR 功能 | 文档演示文本与文件，未证明结果 PNG 一定以图片显示；本次未查到明确许可证 | 只有 Mac 时参考思路做小样，先核验群定位；不直接认定可复制代码 |
| [WeChatPadPro](https://github.com/WeChatPadPro/WeChatPadPro) | iPad 协议服务，HTTP 接口；提供 Docker 部署，依赖 MySQL／Redis | 文档有赞助／VIP 增值支持；未核实当前免费版本登录、授权期限和所需发送权限 | 想用云端时再评估；不是已经确认免费的默认方案 |
| [Wechaty](https://wechaty.js.org/docs/puppet-services/) | 机器人框架＋具体 Puppet／协议提供方 | 框架开源不解决底层接入；服务式适配器通常涉及提供方 token | 适合作接口设计参考；只有落实可用提供方才进入部署候选 |

pywechat 的 [QuickStart](https://github.com/Hello-Mr-Crab/pywechat/blob/main/QuickStart.md) 与 [微信 4.1+ 说明](https://github.com/Hello-Mr-Crab/pywechat/blob/main/Weixin4.0.md) 需要一起读。后者明确报告：部分账号无法取得控件树，启动讲述人已不能普遍解决；部分曾使用无障碍模式的账号仍可见，否则需要 OCR 等界面识别方式。这是维护者报告，未在我们的设备验证。**所以新注册独立账号不能仅凭系统／版本符合就认定可用，先查界面可见性，再写发送逻辑。**

wxauto 的 [Chat 接口文档](https://docs.wxauto.org/docs/class/Chat.html) 提供目标精确匹配、会话类型和发送返回值；可用于设计最小验证，但文档里的函数存在不等于任意客户端都可执行。

协议服务也存在版本失效问题。例如 [LangBot issue #2239](https://github.com/langbot-app/LangBot/issues/2239) 记录了 2026-06 的 WeChatPadPro 登录「版本过低」失败。该报告针对所试镜像，不能推断当前全部版本都失效，也不能仅凭后续仓库有推送就认定问题已解决。部署前必须核对具体服务版本。[项目部署配置](https://github.com/WeChatPadPro/WeChatPadPro/blob/main/deploy/docker-compose.yml)

「iPad 协议」描述的是服务模拟的客户端协议。从其 Docker 部署结构看，不意味着必须购买真实 iPad；这是对部署架构的判断，具体登录仍以选定实现要求为准。

## 3. 旧教程里常见、当前应谨慎区分的名字

- **[Gewechat](https://github.com/Devo919/Gewechat)**：当前 README 明确停止维护并作技术归档，不再提供历史服务端、Docker 镜像和支持；现存代码是 API 调用示例，不能按旧教程当作可直接部署的完整服务。GitHub 仓库的 archived 标记尚为 false，不代表项目仍维护。
- **[WeChatFerry](https://github.com/lich0821/WeChatFerry)**：GitHub 公共 API 显示已归档；README 中适配记录指向微信 3.9.12.51，代码包含 DLL 注入模块。首版不默认选这条需要旧客户端的路线。
- **[chatgpt-on-wechat／CowAgent](https://github.com/zhayujie/CowAgent)**：仓库已更名。当前 [微信接入文档](https://docs.cowagent.ai/channels/weixin) 描述 ClawBot 私聊，不是把独立普通账号拉入现有群。不能把旧群机器人教程与当前官方私聊接入混在一起。
- **[AstrBot 微信个人号通道](https://docs.astrbot.app/platform/weixin_oc.html)**：当前有腾讯 OpenClaw 微信插件接入说明；同样不能仅凭「微信」字样就认为支持普通群。官方通道的群能力边界参见 [OpenClaw 微信文档](https://docs.openclaw.ai/channels/wechat) 与 [本项目研究第 6 节](research.md#6-独立账号与官方机器人通道补查)。

以上排除的是不适合作为本项目当前默认接入的路线，不是说这些框架没有其他用途。

## 4. 对我们开发方案的影响

保留用户已确认的「独立账号＋自动发群＋问卷星优先」。活动程序保持很小：提名队列、校曲、投票、结果图片、每日顺序执行，再接一个微信发送模块。无需为了固定规则投票部署完整 AI 聊天平台，也不需要付费大模型才能计票或生成文案。

| 用户偏好／已有条件 | 建议验证路线 | 实际代价 |
| --- | --- | --- |
| 有可用 Windows 电脑，希望尽量免费 | pyweixin／wxauto4 两者先择一做界面可见性检查 | 发送时电脑开机联网、账号登录、界面可操作；是否锁屏可用需实测 |
| 只有当前 Mac，不想另配设备 | 参考 Mac 项目做文本＋PNG 小样 | 可能短时占用前台和剪贴板，需解决独立账号登录与会话确认 |
| 明确希望电脑关机仍能发 | 核查 WeChatPadPro 或现成娱乐机器人所用的服务端 | 程序和登录会话需要在其他主机运行；服务费用、版本、账号登录是待验证项 |

没有必要现在购买设备／服务。路线选择后，先完成一次用户指定测试会话中的「结果图 → 祝贺 → 提名和链接」发送；第一步成功后再接问卷星业务。仍不在真实运营群试发。

相似项目验证了「有人这样实现」和「可借鉴什么」，尚未验证我们账号的可用性。开发计划 P1 的边界不变。

## 5. 维护状态快照

下表于 2026-09-27 读取 GitHub 公共仓库 API。日期为 `pushed_at` 的 UTC 日期，可能仅是文档／分支推送，不等于最新可用版本，也不能替代 README 的停更声明。没有列出的仓库未在本轮记录 API 快照。

| 仓库／API 来源 | 最近推送（UTC） | archived |
| --- | --- | --- |
| [Hello-Mr-Crab/pywechat](https://api.github.com/repos/Hello-Mr-Crab/pywechat) | 2026-09-26 | false |
| [yunkai/macos-wechat-sender](https://api.github.com/repos/yunkai/macos-wechat-sender) | 2026-09-10 | false |
| [WeChatPadPro/WeChatPadPro](https://api.github.com/repos/WeChatPadPro/WeChatPadPro) | 2026-08-20 | false |
| [Devo919/Gewechat](https://api.github.com/repos/Devo919/Gewechat) | 2026-08-06 | false，但 README 已停止维护 |
| [lich0821/WeChatFerry](https://api.github.com/repos/lich0821/WeChatFerry) | 2026-07-10 | true |
| [oocsoo/WeChatGroupTask](https://api.github.com/repos/oocsoo/WeChatGroupTask) | 2026-05-08 | false |
| [wechaty/wechaty](https://api.github.com/repos/wechaty/wechaty) | 2025-12-21 | false |
| [H4lo/wechatgpt_pro](https://api.github.com/repos/H4lo/wechatgpt_pro) | 2024-09-05 | false |

进入代码复用前再核对所用版本许可证；公开可读、提供 Docker 镜像与开源授权是不同事实。本轮没有引入依赖或复制第三方实现。

## 6. 云端部署物补查

2026-09-27 在用户确认 Azure 额度后，仅查询公开元数据，未下载／执行镜像或登录微信：

- [Docker Hub 标签 API](https://hub.docker.com/v2/repositories/wechatpadpro/wechatpadpro/tags?page_size=10) 返回 latest 与 v18.6，两者为 linux/amd64，同一镜像摘要，更新时间均为 2025-08-25。摘要：`sha256:436685d7d7f9ac690718caba8b8f95ace92ffe6edd2ccfa002459f364ca1282e`。因此当前官方 compose 指向的公开镜像不能直接当作原生 ARM 镜像。
- [GitHub latest release API](https://api.github.com/repos/WeChatPadPro/WeChatPadPro/releases/latest) 返回 v2.01，发布于 2025-08-22；资产包含 Linux amd64 和 arm64 压缩包。这证明有相应架构发布物，不证明当前还能登录。
- [README](https://github.com/WeChatPadPro/WeChatPadPro) 顶部将 v875 指向赞助群，而下载表仍描述较旧版本；系统要求写至少 2 GB 内存，依赖 MySQL／Redis。不能把旧公开镜像认作最新免费可用版本，不能按 1 GB 主机承诺完整部署。
- [wechat-robot-client 快速开始](https://wechat-doc.houhoukang.com/guide/getting-started) 说明初始配置默认启用 AI，同步历史消息可能触发回复。若评估该套件，必须先关闭自动回复与历史同步，才能用指定测试会话验证发送；不使用默认配置直接登录正式活动账号。其服务端费用／许可问题仍未核实。

当前判断：先弄清可获取、可授权使用且支持当前登录的具体微信服务版本，再确定 Azure 规格。已有云赠金额度并没有消除微信接入这一待验证项；本轮未认定所有免费版本都失效。
