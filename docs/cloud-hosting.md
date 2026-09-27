# 免费云端运行方案

最新范围（D008）：提名与投票完全自建，取消问卷星 API 依赖。先开发和验证网站，不等待微信协议服务选定；本页原有问卷星架构与依赖次序保留为早期调研记录，现行步骤见 [开发计划](development-plan.md)。

查证日期：2026-09-27。用户已明确希望日常运行不依赖本地电脑。本轮仅查阅供应商官方资料，未注册、绑卡、领取额度或创建资源。具体账户资格、区域库存、账单与微信登录均未实测。

最新进展：用户确认 Azure 认证已完成，有可用学生赠金，具体额度与到期时间在本机维护，尚未创建虚拟机；助手未登录或创建资源。订阅显示名称／状态在实际访问时再核对。建议 Azure 先作开发验证，Oracle 保留作长期免费候选。学生赠金用于云资源，不是微信协议服务预算。

## 结论与候选

有免费云资源，但「长期免费主机」「限期赠金」「免费函数」不同。微信接入服务能否免费运行，也独立于服务器是否免费。当前优先考虑可运行 Linux 服务的云端协议路线；不能直接将 Windows 自动化程序搬到 Linux 主机。

| 方案 | 官方当前权益 | 适合本项目的程度 |
| --- | --- | --- |
| Oracle Cloud Always Free | A1 ARM 合计 2 OCPU／12 GB，另有最多两台 AMD Micro（各 1 GB）；免费主机须在主区域，存在容量不足及空闲回收 | 长期零服务器费的主要候选；必须先核对微信服务的 ARM 支持，不能把两台小机器的内存视为单台可用 |
| Azure for Students | 合资格全日制大学生可免信用卡申请，100 美元额度在 12 个月内使用，在校可按条件续领；部分服务有免费配额 | 有学生资格时适合开发验证；不保证赠金够任意服务器全年运行，需计入磁盘、网络等费用；学生资格和用途条件待核实 |
| Google Cloud Free Tier | 美国指定三区一台 e2-micro 的月时数，30 GB 标准持久磁盘；出站免费额度有地域限制 | 有长期免费计算额度，但常用公网 IPv4 另收费，不作为完整零成本首选 |
| 阿里云个人 ECS 试用 | 当前页面列 300 元额度、3 个月有效，需实名认证和产品新用户资格 | 可作临时验证环境，不能作为长期免费承诺 |
| 腾讯云轻量试用 | 官方活动页有个人 1 个月试用，配置／名额依页面及账户而定 | 同上，适合先验证，期满另作选择 |
| AWS 新账户 Free Plan | 最长 6 个月或赠金用尽，以先到为准 | 限时方案，不能沿用旧教程「EC2 新用户免费一年」 |

来源：[Oracle 配额及回收规则](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)、[Azure 学生方案](https://azure.microsoft.com/en-us/free/students)、[Azure 资格条款](https://azure.microsoft.com/en-us/pricing/offers/ms-azr-0170p)、[Google 免费配额](https://docs.cloud.google.com/free/docs/free-cloud-features)、[阿里云试用](https://free.aliyun.com/)、[腾讯云试用](https://cloud.tencent.cn/act/pro/free)、[AWS 免费计划](https://aws.amazon.com/free/free-tier-faqs/)。

## 三项影响选择的细节

1. **Oracle 的免费配额与旧教程不同。**当前文档写 2 OCPU／12 GB，不能沿用 4 OCPU／24 GB。官方允许回收连续 7 天满足低 CPU／网络利用率等条件的免费实例，ARM 还考虑内存。本项目每天只执行少量任务，可能触及空闲条件；这是基于工作负载的判断，不代表一定被回收。不通过人为消耗资源规避回收。
2. **Oracle 通常需手机号和信用卡验证。**其文档说明不升级账户不会扣款；保持免费账户，不把注册验证当成付费升级授权。是否能注册及主区域是否有免费库存，以实际账户为准。[账户说明](https://docs.oracle.com/iaas/Content/FreeTier/freetier.htm)
3. **Google 的免费 VM 不等于完整免费账单。**标准 VM 公网 IPv4 为 0.005 美元／小时，每月仅 1 小时免费；按 30 天持续使用估算约 3.60 美元／月，仅 IP 一项。IPv6 地址免费也不证明微信所需所有端点都能纯 IPv6 访问，不为省这项费用预先设计复杂中转。[网络价格](https://cloud.google.com/vpc/network-pricing)

## 不作为常驻微信服务的免费方案

- **Cloudflare Workers** 可用于轻量定时 HTTP 调用或投票 API，免费档每天 10 万请求，但 CPU 时间每次仅 10 ms（含 Cron）。它不是可直接运行任意 Docker 镜像的传统 VPS，不能默认承载现成微信协议服务或完整图片渲染流程。只有另有可用发送 API 时才有意义。[限制](https://developers.cloudflare.com/workers/platform/limits/)、[定时触发](https://developers.cloudflare.com/workers/configuration/cron-triggers/)
- **Render 免费 Web 服务** 15 分钟没有入站流量会休眠，重启／休眠丢失本地文件。不适合直接放依赖持续登录和本地状态的微信服务；不使用保活请求绕过免费机制。[免费档说明](https://render.com/docs/free)

本轮未找到可以直接推荐的长期免费 Windows 云桌面。因此本地 UI 自动化退为参考；若协议路线不通，再与用户讨论云 Windows 的额度和运行条件，而不是要求用户电脑保持开机。

## 云端部署草案与下一步

```text
云主机：每日任务 + SQLite + 结果 PNG + 微信发送服务
             ↕                         ↓
          问卷星                 独立微信账号 → 现有群
```

这是待验证草案。用同一台主机运行可简化部署；具体协议服务如必须有 MySQL／Redis，则另记真实依赖，不宣称 SQLite 能替代它们。

推荐顺序：

1. 用户已提供余额、到期日和无虚拟机状态，足以继续研究。实际创建前再核对订阅状态与免费配额；无需发送证件、卡号、密码或访问密钥。后续余额可在 [Azure Sponsorships 门户](https://www.microsoftazuresponsorships.com/) 查看。[微软说明](https://learn.microsoft.com/en-us/azure/education-hub/azure-dev-tools-teaching/azure-students-program)
2. 核对微信服务版本、授权费用、CPU 架构及群文字／图片接口。已查询 WeChatPadPro Docker Hub 架构：公开 latest／v18.6 为 linux/amd64；公开 GitHub Release 另有 Linux ARM64 压缩包，两者不能混为同一部署物。详见 [相似项目补查](related-projects.md#6-云端部署物补查)。
3. 合资格时优先将 Azure 学生额度作为开发验证候选；长期零服务器费优先尝试 Oracle，但不保证库存与免回收。资格不满足时保留国内限期试用，不自动改为购买。
4. 在用户选定平台后，核对创建页的实例、系统盘、IP、流量和总价；只使用已确认免费权益，不自动升级账户。按实际服务要求选最小可用配置，不先承诺 1 GB 足够整个协议栈。
5. 云端小样只在指定测试会话中发送 PNG 与文本。用户电脑关机后仍能执行，才满足新的日常运行要求；掉线后仍可能需要本人手机重新扫码。

服务器、微信接口、问卷星 API 三项分别记录免费／可用情况。任何一项尚未验证，都不将整个机器人标为免费可上线。
