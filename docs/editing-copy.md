# 文案与视觉修改指南

本项目用 HTML 模板直接生成网页。改页面上的话，通常只需打开对应模板，在编辑器中搜索现有文案，然后替换它。无需修改数据库或安装前端工具。

## 常改的文案在哪里

以下路径均相对于项目根目录，点击链接可打开文件。

| 想改的内容 | 文件 | 搜索提示 |
| --- | --- | --- |
| 站点名、浏览器标题后缀、顶部导航、页脚 | [base.html](../cricket/templates/base.html) | `今天你滚了吗`、`今日对决`、`活动管理` |
| 首页大标题、副标题、投票按钮、封面缺失说明、底部提名邀请 | [round.html](../cricket/templates/round.html) | `每日斗蛐蛐`、`每天两首`、`投这首`、`下一场` |
| 提名页标题、填写提示、昵称、备注、提交按钮 | [nominate.html](../cricket/templates/nominate.html) | `下一场`、`请尽量规范填写`、`怎么称呼你`、`放进提名箱` |
| 两首歌的通用字段名称与输入提示 | [macros.html](../cricket/templates/macros.html) | `艺人`、`曲名`、`网易云音乐链接` |
| 提名成功页 | [thanks.html](../cricket/templates/thanks.html) | `收到`、`两首歌已经进入` |
| 管理员登录页 | [login.html](../cricket/templates/login.html) | `管理员入口`、`管理密码` |
| 管理员实时票数、刷新与状态文案 | [_live_votes.html](../cricket/templates/_live_votes.html)、[app.js](../cricket/static/app.js) | `正在进行的投票`、`刷新票数`、`更新失败` |
| 管理后台标题、按钮与说明 | [admin.html](../cricket/templates/admin.html) | `每日安排`、`提名队列` |
| 曲目审核页、曲库搜索页、轮次预览页 | [review.html](../cricket/templates/review.html)、[music.html](../cricket/templates/music.html)、[round_admin.html](../cricket/templates/round_admin.html) | 直接搜索页面原句 |
| 提交成功／失败后的提示条 | [__init__.py](../cricket/__init__.py) | 搜索 `flash(`，例如 `已记下你的选择` |
| 数据校验错误提示 | [service.py](../cricket/service.py) | 搜索 `raise ValueError` |
| 群内当天歌曲消息 | [service.py](../cricket/service.py) 的 `nomination_message` | `今天的曲目`、`投票链接` |
| 群内祝贺、平局、零票消息 | [service.py](../cricket/service.py) 的 `congratulations` | `让我们恭喜`、`双方都很能打` |
| 结果 PNG 上的文字 | [poster.py](../cricket/poster.py) 的 `render`／`match_panel` | `每日斗蛐蛐`、`WINNER / 胜出`、`平局` |

网页、群消息、结果 PNG 是三处独立输出。例如，改网页标题不会改变 PNG 标题；需要统一时，按表格修改对应文件。

## 怎样改，不影响功能

例如在 `round.html` 中，把：

```html
<p class="hero-caption">选出你认为更好的一首歌</p>
```

改成：

```html
<p class="hero-caption">今天，让哪一首留下来？</p>
```

只替换中文句子，保留 HTML 标签及其属性。模板里的 `{{ ... }}` 是动态数据，`{% ... %}` 是循环／条件；不要删掉。按钮的 `name`、`value`、表单的 `action` 和隐藏的 `csrf` 用于提交投票，改按钮文字时保持它们不变。

`service.py` 中的 `{变量}` 会填入艺人、歌名或链接，调整句式时保留所需变量。`winner_label` 是胜者命名规则，单纯改语气无需改它。

改静态标签不会修改队列里实际的艺人／曲名；那些信息应在后台审核页面核对。已排期的曲目是历史快照，不能通过改模板纠正。已准备的群消息也存有快照，改生成函数不会自动重写已有草稿。

## 如何查看效果

当前演示地址为 http://127.0.0.1:5057/today ，只在本机服务运行期间可访问。

- **CSS**：保存后刷新网页；缓存未更新时强制刷新。
- **HTML／Python**：当前预览使用 Gunicorn，需要重新加载工作进程。自己从终端启动时，可以按 Ctrl+C 停止，再运行原启动命令。
- **PNG**：重启后重新打开对应结果图片地址；已导出的本地图片不会自动改变，需要重新导出。

自行启动演示可用：

```sh
DEMO_MODE=1 DATABASE=data/demo.sqlite3 uv run python -m cricket serve
```

已有示例数据库不用重新执行 `demo`。修改表单或消息生成逻辑后可运行 `uv run pytest -q`；只是换一句页面介绍，不必为每句文案加测试。

页脚的“最近对决”由 `round.html` 的 `footer_history` 区块提供，活动管理链接在 `base.html`。标志及浏览器图标共用 [brand-mark.svg](../cricket/static/brand-mark.svg)。

管理登录页与 `/admin` 下的后台页面不显示公共页脚，避免重复出现活动管理入口。

## 改颜色、字体与间距

统一在 [style.css](../cricket/static/style.css)。文件已按布局、组件和手机断点分段；开头 `:root` 定义公共颜色。

| 位置 | 控制内容 |
| --- | --- |
| `:root` 的 `--paper`、`--surface` | 页面背景、白色内容区域 |
| `--ink`、`--muted`、`--accent`、`--action` | 正文、辅助文字、音乐红点缀、深红操作按钮 |
| `body` 的 `font-family` | 系统字体；无需下载额外字体 |
| `h1`、`.song h2`、`.artist`、`.album` | 标题、曲名、艺人、专辑的层级 |
| `.site-header`、`main`、`.page-heading`、`footer` | 页头、标题区、页脚的上下留白；main 不设强制最小高度 |
| `.duel`、`.songs`、`.song-body` | 一组对决的容器、两栏与歌曲信息布局 |
| `.cover`、`.listening`、`.duel-foot` | 封面尺寸、听歌链接间距与底部留白；桌面封面 176px，中等宽度 144px，手机随列宽缩放 |
| `.nomination-form`、`.form-footer` | 提名表单容器与居中大按钮；公开提名仅填写艺人和曲名，链接字段仅在审核表单显示 |
| `.cover.absent` 及伪元素 | 缺失封面时的 CSS 唱片示意；不是实际专辑封面 |
| `.vote-button`、`.vote-button.chosen` | 未选／已选按钮 |
| 文件后半的 `@media` | 平板、手机及减少动态效果的设置 |

当前方向：参考 Apple Music 的清晰层级，用黑白底色、音乐红与黑胶唱片细节加强音乐社群个性；保持对齐与留白，方形图标为红底白字。曲目名允许自然换行，不用截断隐藏信息。桌面与手机保持两首并排比较，后台和表单沿用同一套视觉规范。

投票卡片以封面和歌曲信息为主，内部间距保持紧凑；手机歌曲说明不设置固定最小高度，由内容撑开并保持投票按钮对齐。


## 小动效的位置

[style.css](../cricket/static/style.css) 的 `surface-arrive` 控制卡片轻入场，`selection-settle` 控制勾选反馈；`@media (hover:hover)` 内控制可点击标志和导航的悬停反馈，`:active` 控制按钮按压。时长约 0.2–0.4 秒，无持续转动。

[app.js](../cricket/static/app.js) 的 IntersectionObserver 让每个区域只入场一次；没有脚本时内容也完整显示。保留文件末尾 `prefers-reduced-motion` 的无动画分支，避免影响选择减少动态效果的用户。

封面当前仅展示曲目信息，不可点击，因此没有悬浮／位移动效；听歌操作通过音乐平台链接完成。

## 历史赛果与结果海报

历史页在 `round.html` 的 `result-summary` 显示胜出曲目与票差；`.is-winner`、`.score`、`.result-meter` 在 `style.css` 中控制胜者底色、大票数和得票比例。进行中的投票不会显示这些结果。

结果 PNG 的独立视觉布局在 `poster.py`：`render` 控制刊头、日期、页脚与分页，`match_panel` 控制双封面、曲目信息、票数与胜负标记。开头的颜色常量与字号可直接调整；文字高度先测量再布局，修改时保留此机制以免长歌名被截断。封面下载与缓存逻辑单独放在 `artwork.py`，不在排版代码中修改来源。

## 自动提名处理

处理状态、纠错对照、缺失链接说明和手动修正入口在 `review.html`；队列状态在 `admin.html`。来源选择、缺失规则和错误原因在 `enrichment.py`；拼写与版本规则在 `matching.py`，更改这些规则需要同步 `docs/nomination-pipeline.md` 及回归测试。
