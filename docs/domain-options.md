# 免费域名候选

查证日期：2026-09-27。第三方候选为公开资料调研，未注册或验证名称可用性。用户随后要求先缩短现有 Azure 域名，已改为 https://pkudigger.eastasia.cloudapp.azure.com，见 D021；下文第三方候选仍未选定。

现有 Azure 静态公网 IP 可以绑定其他域名，不需迁移应用或数据库。长期免费候选主要是第三方提供的子域名；独立域名的学生优惠通常只覆盖首年。

| 方案 | 候选形式（未注册） | 条件与判断 |
| --- | --- | --- |
| DuckDNS | `pkudigger.duckdns.org` | 官方提供免费子域名，可指向指定 IP。作为简单直接的备选；用户更偏好短后缀，补查见下。 |
| FreeDNS | `pkudigger.mooo.com` | 免费共享子域名。官方建议长期使用选择平台管理者持有的后缀，如 mooo.com；其他用户共享的后缀存在持有人撤回等依赖。作为备选。 |
| No-IP | 自选名称＋平台免费后缀 | 当前免费方案 1 个主机名，每 30 天需确认，增加维护负担，不优先。 |
| GitHub 学生包 | 如 `pkudigger.me`、`pkudigger.studio` | Namecheap 提供 .me 首年免费；Name.com 提供指定后缀首年免费，具体资格、名称和续费价格在领取时核对。Azure 学生认证不能当成已完成 GitHub 学生资格。适合接受后续续费者。 |
| EU.org | `pkudigger.eu.org` | 官网仍列免费子域名服务，欢迎非欧洲及非营利用途；没有验证当前申请处理速度或实际获批，不作为立即切换的首选。 |
| is-a.dev | `pkudigger.is-a.dev` | 限与软件开发有关的个人／非商业项目，需 GitHub PR 审核；本项目实际面向音乐活动，用途适配不如通用子域名，不优先。 |

免费表示当前服务／优惠规则，不保证永久运营。上述候选未经过中国大陆手机微信网络验证。

## 短后缀补查（同日）

用户要求扩大免费渠道检索。上一轮漏掉了 DigitalPlat 与 DNSHE 等短子域名平台；以下均为官方公开页面核对，不代表已取得免费名额或注册成功。

| 平台 | 候选形式（未查注册可用性） | 已核实的公开条件 |
| --- | --- | --- |
| DigitalPlat | `pkudigger.qzz.io`、`pkudigger.dpdns.org`、`pkudigger.us.kg` | 官网列出这些后缀并提供免费注册；FAQ 默认每账户 1 个免费名额。支持外部 NS，需另配权威 DNS 再指向 Azure，不锁定托管平台。最新续期文档要求以控制台逐后缀核对窗口和费用，不能照旧教程承诺永久免费续期。 |
| DNSHE | `pkudigger.cc.cd`、`pkudigger.us.ci`、`pkudigger.bot.cd` | 官网提供免费注册、A 等记录及外部 NS；无需信用卡、不强制广告。默认有效期一年，到期前 180 天内可免费续期，官方公告称续期次数不限，需正常真实使用。 |
| NIC.UA 的 PP.UA | `pkudigger.pp.ua` | 注册和续期价目均为每年 0 UAH，任意个人／组织可申请；需有效手机号码激活，支持短信／Telegram 路径，当前用户号码的实际可达性未验证。注册资料公开规则需在申请时核对。 |

按“短、免费、绑定已有服务器”的新偏好，可先尝试 DNSHE 的 `pkudigger.cc.cd`；偏好 .io 结尾时尝试 DigitalPlat 的 `pkudigger.qzz.io`，先查账户实际免费与续期条件。这些是平台分配的子域名，`pkudigger.qzz.io` 不等于独立注册 `pkudigger.io`，但可正常用作本站地址。

没有查到面向普通用户、可核实的独立 `.io`／`.mv` 持续免费注册方案。学生独立域名的实际可选后缀包括 `.me`、`.tech` 及 Name.com 的指定后缀，仍是首年优惠。js.org 要求内容明确关联 JavaScript，不适合仅为换后缀而申请本音乐投票站。Freenom 搜索仍出现历史免费页面，未验证能完成当前新注册，不列为可用推荐。

DigitalPlat 控制台此次网页抓取返回 403，未登录、未绕过验证、未验证名称；DNSHE 公开查询要求人机验证，未宣称候选可注册。

补查来源：

- [DigitalPlat 后缀与服务](https://domain.digitalplat.org/) · [免费名额 FAQ](https://github.com/DigitalPlatDev/FreeDomain/blob/main/documents/domains/faq.md) · [当前续期规则说明](https://github.com/DigitalPlatDev/FreeDomain/blob/main/documents/tutorial/platform/1.4-status-and-renewal.md)
- [DNSHE 官方方案和 FAQ](https://www.dnshe.com/) · [年度免费续期公告](https://my.dnshe.com/announcements/6/DNSHE-Free-Domain-Registration-Duration-Adjustment-Notice-Introduction-of-an-Annual-Registration-System.html?language=chinese)
- [NIC.UA 注册及续期报价](https://nic.ua/en/domains/.pp.ua) · [PP.UA 规则](https://pp.ua/eng/policy.html)
- [JS.ORG 用途条件](https://js.org/) · [Freenom 当前入口](https://my.freenom.com/domains.php)

## 切换步骤

1. 用户选择后缀和名称，在自己的账户完成注册／必要认证；凭据保存在忽略路径，不写入文档。
2. 添加指向当前 Azure 静态公网 IP 的 A 记录，核对解析。
3. 配置 Caddy 为新域名取得免费 HTTPS 证书，再更新 app／worker 的 PUBLIC_BASE_URL。沿用当前服务器和数据库。
4. 验证提名、投票、管理登录、结果图片及手机微信访问；旧域名可保留并重定向到新域名，避免历史链接失效。
5. 浏览器身份与管理员登录 Cookie 不跨域迁移。对本项目尤其应在两轮之间切换，避免同一人因新域名获得新投票标识。

## 官方来源

- [DuckDNS 服务介绍](https://www.duckdns.org/about.jsp) · [接口](https://www.duckdns.org/spec.jsp)
- [FreeDNS](https://freedns.afraid.org/) · [FAQ：共享域名与长期使用建议](https://freedns.afraid.org/faq/)
- [No-IP 免费方案](https://www.noip.com/free) · [30 天确认规则](https://www.noip.com/support/knowledgebase/why-is-my-hostname-missing-or-deleted-what-do-i-do)
- [GitHub Student Developer Pack](https://education.github.com/pack) · [Name.com 学生首年优惠说明](https://github.com/namedotcom/student-pack) · [Namecheap 学生入口](https://nc.me/)
- [EU.org](https://nic.eu.org/) · [政策](https://nic.eu.org/policy.html)
- [is-a.dev 注册条件](https://docs.is-a.dev/quickstart/)
