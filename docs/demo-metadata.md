# 示例曲目、链接与封面核验

核验日期：2026-09-27。公开元数据保存在 `cricket/demo_tracks.json`，新建演示库直接使用该文件；现有隔离演示库也已补齐。演示昵称和票数仍为虚构样本。

按用户后续确认，重制版默认接受，示例的展示用 `version` 留空；下表及 `platform_evidence` 中的重制信息仅用于来源留存，不作为页面标注或选版限制。

| 曲目 | 网易云 | Apple Music 中国区 | 封面对应发行与版本说明 |
| --- | --- | --- | --- |
| Deep Purple — April | [曲目](https://music.163.com/song?id=4021290) | [曲目](https://music.apple.com/cn/song/695558807) | [Deep Purple](https://music.apple.com/cn/album/695558790)，Apple 收录于 Bonus Tracks Version；两边明确标注 2000 年重制版 |
| Pink Floyd — A Saucerful of Secrets | [曲目](https://music.163.com/song?id=4238558) | [曲目](https://music.apple.com/cn/song/1065974584) | [A Saucerful of Secrets](https://music.apple.com/cn/album/1065974579)，同名正式专辑 |
| The Smiths — There Is a Light That Never Goes Out | [曲目](https://music.163.com/song?id=19576478) | [曲目](https://music.apple.com/cn/song/800157892) | [The Queen Is Dead](https://music.apple.com/cn/album/800092985)；网易云明确标注 2011 年重制版，Apple 标题未标重制年份 |
| Mötley Crüe — Home Sweet Home | [曲目](https://music.163.com/song?id=400349400) | [曲目](https://music.apple.com/cn/song/1764393261) | [Theatre of Pain](https://music.apple.com/cn/album/1764393010)，封面选正式专辑；网易云收录于 Deluxe Version |

## 实际验证

- 八个公开歌曲页面均返回成功响应，核对页面标题、艺人和曲名；结合平台目录核对专辑、时长与版本标记。保留各平台原始名称和时长，不将近似时长视为完全相同母带的证明。
- 四张 600 × 600 封面 URL 均取自对应 Apple Music 中国区专辑页面，保留 `artwork_source`；本地浏览器已确认全部图片加载成功。
- 网易云使用其公开搜索与歌曲详情接口进行一次性元数据读取（`/api/search/get/web`、`/api/song/detail/`）；这不等于平台提供稳定、受支持的开发者 API，也没有加入网站的运行时自动抓取流程。
- 未登录验证完整播放权益，未验证手机微信内跳转。公开页面可访问不代表所有地区、账号均能完整播放。
- 原始查询响应位于忽略目录 `output/music-verification/`。可提交的公开来源、选版信息和核验日期保存在 JSON 中。

## 数据变更范围

本次先备份 `data/demo.sqlite3`，仅补齐四首已知示例曲目的提名、对决及演示历史快照元数据；保留现有投票、提名状态和其他记录。历史快照的补齐仅针对隔离演示库，不改变正式活动截止后冻结结果的规则。

临时空库重新生成演示数据通过验证：两天四组对决均具有封面、双平台链接和来源证据。
