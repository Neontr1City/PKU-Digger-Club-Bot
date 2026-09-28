# 管理员邮件通知

查证日期：2026-09-28。用户已选 QQ 邮箱。通知代码与隔离测试已完成并部署；Azure 到 QQ SMTP 465 的 TLS 连接及证书校验实测通过。真实账号已配置，连接测试邮件已由 QQ SMTP 接受，app／worker 均已启用自动提醒。用户已确认收到测试邮件。

## 开通与配置

1. 在 QQ 邮箱网页版进入设置／账号，开启 IMAP/SMTP 或 POP3/SMTP 服务，按页面要求完成验证并生成专用授权码。使用授权码而非 QQ 登录密码。
2. 本项目已经准备私有文件 `output/deploy/qq-mail.env`，只需填写 `QQ_SMTP_EMAIL` 和 `QQ_SMTP_AUTH_CODE`。`ADMIN_EMAIL_TO` 留空则给同一 QQ 邮箱发信。该文件为部署交接文件，不会被程序或源码打包器自动加载。
3. 将配置安全写入正式服务器 `.env.local`，先保留 `ADMIN_EMAIL_ENABLED=0`；仅在测试进程临时启用开关，运行 `python -m cricket mail-test`，向固定收件人发送连接测试邮件。不要把凭据写进源码、命令行参数或可输出的日志。
4. 测试提交成功后，正式配置设 `ADMIN_EMAIL_ENABLED=1`，重新创建 app 和 worker，并由收件人确认收到邮件。QQ 接受邮件不等于已进收件箱，必要时检查垃圾邮件。

程序固定使用 QQ 的 `smtp.qq.com:465` 和 SSL 证书校验，无第三方付费服务，无需网站域名的邮件 DNS 配置。Python 使用标准库发信，无新增依赖。默认关闭，DEMO_MODE=1 时不允许发信。

## 通知规则

- 提名处于 pending、查找进入 review 时提醒；邮件含编号、原始艺人／曲名、处理原因和登录后台的链接，不含昵称、管理密码或授权码。
- 曲库请求失败仍由原流程每 15 分钟重试，最多尝试 3 次；耗尽才提醒。短暂错误、queued／running 不发信。
- 已接受的单平台链接或封面缺失不发通知；ready、scheduled、skipped 不通知。
- 邮件说明该组未就绪将阻塞按序排期，不另发每天重复的阻塞提醒。
- 每组提名在 SMTP 接受后只记录一次，人工重新查找仍不重复提醒。暂未配置前产生的待处理提名，会在启用后补提醒；发送前已解决的不会通知。
- 发送失败在 15、30 分钟后重试，之后最多每小时一次；重新检查当前状态，已解决或跳过的不再重试。失败记录不保存 SMTP 原始异常，避免暴露凭据。
- SQLite 保存发送状态、尝试次数与 Message-ID，正常重启不会重复发送。网络中断或 SMTP 已接受但进程尚未写回时可能重发；SMTP 无法保证端到端严格仅一次，重试复用 Message-ID。
- 邮件在独立工作线程发送，每分钟最多尝试一组，不阻塞网页提交／投票，也不阻塞整分钟排期。没有 worker 就没有自动邮件。

## 实现与验证边界

`notifications.py` 选择真实待处理项，`email_notifications` 保存发送状态，worker 调用发信。旧数据库启动时自动增加新表；不改曲目、票数或结算规则。隔离测试覆盖接受缺失项、不满足条件不通知、去重、失败重试、问题已解决、并发领取／崩溃恢复、TLS 与 SMTP 认证、停用和演示隔离。已完成真实账号 SMTP 认证和测试邮件提交，QQ 返回接受，且用户已确认收到测试邮件，实际发信链路已验证。

## 已核实的外部能力

- 腾讯 CloudBase 官方配置文档列出 QQ 邮箱 smtp.qq.com 与 SSL 465，可用普通邮箱作为程序发件账户：https://intl.cloud.tencent.com/zh/document/product/1266/71700 。具体账户是否已开通需实测；不沿用表中另一端口的排印错误。
- 华为官方客户端支持说明记录 QQ 邮箱启用 SMTP 并生成授权码的操作：https://consumer.huawei.com/cn/support/content/zh-cn16108643/ 。登录密码与客户端授权码分开。
- Brevo 官方免费计划包含事务邮件，每日 300 封：https://help.brevo.com/hc/en-us/articles/208589409-About-Brevo-s-pricing-plans 。这是可选后备，未注册或选定；免费邮箱作为其发件人有认证和投递限制，不能只根据免费额度就保证适用：https://help.brevo.com/hc/en-us/articles/35852083084178-Domain-setup-for-better-email-deliverability 。
