# 公告原文回归样本

采集时间：2026-10-29 22:08（Asia/Shanghai）。来源为 PRTS API action=parse、prop=wikitext。
这些是人工节选，不是完整公告；删除了图片、无关奖励清单和无关板块，保留影响解析的原始标题、标点、换行、阶段时间、兑换时间和引用语法。无意把网页后续变动作为测试输入；测试全程离线。

- 庆典2026.wikitext：https://prts.wiki/w/感谢庆典2026/活动公告
- 庆典2025.wikitext：https://prts.wiki/w/感谢庆典2025/活动公告
- 矢量突破03.wikitext：https://prts.wiki/w/矢量突破/03/活动公告
- 限时签到活动页.wikitext：https://prts.wiki/w/感谢庆典2026限时签到

测试分两类：通过项验证当前正确的数据链；strict xfail 项表达已确认的机制缺陷，不把错误行为当基准。修复导致 XPASS 时必须移除相应 xfail。没有全量历史覆盖、CSV写回或渲染验收。
