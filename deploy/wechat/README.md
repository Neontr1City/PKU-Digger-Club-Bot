# 原服务器上的微信客户端与发送程序

这是可选的官方客户端环境，包含本项目界面发送适配器。网站默认关闭自动发送；明确配置目标群后才启用。客户端独立于网站 Compose，启用后使用 `unless-stopped` 在主机恢复时启动。官方客户端是专有软件，构建时从腾讯官网下载并校验本次记录的 SHA-256；不将客户端或登录状态提交仓库，也不修改客户端。

适用：已有本项目 Docker Compose 网站、Linux amd64、`deploy_default` 网络。先核对服务器余量。本目录采用独立构建上下文，不包含网站配置或密钥。

## 构建与启动

从项目根目录执行；在小内存服务器使用有资源限制的构建步骤：

```sh
DOCKER_BUILDKIT=0 docker build --memory=256m --memory-swap=640m \
  --cpu-period=100000 --cpu-quota=75000 \
  -t pku-digger-wechat:4.1.13.23 deploy/wechat
sudo install -d -m 0700 -o 10001 -g 10001 data/wechat
docker compose -p pku-wechat -f deploy/wechat/compose.yaml up -d
```

经典构建器用于约束当前小主机的构建过程，属于 Docker 已弃用路径；若未来版本不支持，不直接改成无资源限制构建。运行上限为 512 MiB 内存、1024 MiB 内存与 swap 总计、0.75 CPU、1024 个进程／线程；并非实测最低需求。最初 320 MiB、随后 448 MiB 上限在登录同步时频繁触发回收，确认宿主余量后调整，未扩容 VM 或增加宿主 swap。达到上限可能退出；先查看资源事件再调整，不以重复登录或扩大资源替代排障。

`pids_limit` 同时计算线程，不能按群消息数量设置。最初 256 上限在三次登录后崩溃时均留下内核 `fork rejected by pids controller` 记录；GDB 显示 `mars::stn` 线程在 `pthread_detach` 段错误，因此放宽到 1024 后重新验证。退出时记录 pids 与内存事件计数，便于区分限制触发和其他故障；不以放宽上限替代实际验收。

Xvfb 提供虚拟显示、Openbox 管理窗口、x11vnc 只监听容器回环地址，websockify 提供 noVNC 页面。没有额外浏览器、完整桌面或多账号面板。容器无宿主公开端口、非 root 运行、无额外 Linux capabilities；仅连接网站 Docker 网络。发送程序只在私有 `bot-outbox/config.json` 存在时启动；每条发送前核验当前群聊，不自动打开或猜测目标。

## 管理员访问

网站使用新版 `deploy/Caddyfile` 和 `cricket` 的访问校验路由。需在服务器私有 `.env.local` 显式设 `WECHAT_DESKTOP_ENABLED=1`，重建／重启 app 并验证、重载 Caddy 配置。随后登录 `/admin`，点击「打开云端微信」。

- 每个页面、静态文件及 WebSocket 握手均由 Caddy 向 app 校验当前管理员会话；未登录转到登录页，关闭开关或演示环境拒绝访问。
- 拒绝携带其他站点 Origin 的请求；转发到桌面前移除 Cookie 和 Authorization。只通过现有 HTTPS 访问，不公开 5900／6080 端口。
- 已建立的桌面连接最长 30 分钟，到期需重新连接并校验；退出网站不会瞬间撤销已建立的连接。紧急撤销请停止微信容器。
- 微信登录由用户本人扫码、确认，不索取微信密码。登录状态存 `data/wechat/`；客户端日志位于容器 `/tmp`，不输出原始日志到公共聊天，不保存扫码截图。

## 查看占用与停止

```sh
docker compose -p pku-wechat -f deploy/wechat/compose.yaml ps
docker stats --no-stream
docker compose -p pku-wechat -f deploy/wechat/compose.yaml stop
```

停止容器立即断开远程桌面并释放运行内存，保留登录目录。网站仍可使用；关闭桌面入口需将私有配置开关设回 `0` 并重新创建 app。不要删除 `data/wechat/` 来处理普通运行故障。

自动发送的配置、状态、掉线邮件与异常恢复见 [推送说明](../../docs/wechat-delivery.md)。

首次真实验收必须分别记录：启动界面、扫码、目标测试群核验、文字与 PNG 发送、网站健康、内存与 swap 实际占用。启动成功不等于登录后或长期运行已验证。当前指定目标仅「PKU Digger Bot测试」。

## 临时崩溃诊断

`Dockerfile.debug` 基于当前运行镜像，仅为有人操作的诊断额外安装 Ubuntu 源的 GDB。它设置 `WECHAT_DEBUG=1`，用调试器启动同一官方客户端；禁用 core dump，不输出函数参数，诊断日志只留在容器 `/tmp/wechat-debug.log`，不得提交 Git 或完整贴到公共聊天。仍使用原有用户、权限和资源约束，不自动重试登录或发送。

正常 Compose 不选用诊断镜像。服务器临时覆盖文件位于忽略目录 `output/wechat-probe/debug-compose.yaml`；结束诊断后用常规构建与 Compose 恢复普通镜像，保留 `data/wechat/`。启用调试器只提供崩溃证据，不表示已经修复客户端问题。
