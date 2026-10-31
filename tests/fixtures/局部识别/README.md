# 局部识别离线真实样本

本目录六份完整wikitext由2026-10-29的隔离试验缓存复制，不是本次正式迁入时重新抓取。测试零网络，人工期望来自原文日期/区域，不由提取器生成。

| 文件 | 来源页 | 年份依据 | 获取方式 | SHA256（UTF-8原文） |
|---|---|---|---|---|
| 感谢庆典2026.wikitext | https://prts.wiki/w/感谢庆典2026/活动公告 | 2026 | 先前隔离缓存 | b04459a3362e124dc962413ac9cbaf381067c6b726dda9a453ae8400a3c3f384 |
| 感谢庆典2025.wikitext | https://prts.wiki/w/感谢庆典2025/活动公告 | 2025 | 先前隔离缓存 | 0e900583b72dee15568c7bff2c845cbe14e8d0f78ef461d7e0f7d030c4bf6763 |
| 生路.wikitext | https://prts.wiki/w/生路/活动公告 | 2024 | 当时MediaWiki parse API | d3b0de86730adfef4280ef6dac6332c485db38c1a33e36fc4531f972fc727d9a |
| 生路2025.wikitext | https://prts.wiki/w/生路2025/活动公告 | 2025 | 当时MediaWiki parse API | f3307bb8b210e53fd2329945876e1bb856e70a700c05468b0599a5ad4a6ee610 |
| 孤星2024.wikitext | https://prts.wiki/w/孤星2024/活动公告 | 2024 | 当时MediaWiki parse API | 7b94a1cbd0a16ebb43b48e0ec711973a95ed3264d6cae79f7f04ceddfd4652da |
| 孤星.wikitext | https://prts.wiki/w/四周年庆典/活动公告 | 2023 | 当时MediaWiki parse API | 386f99e171b6192cda59efb07f43db5e0af5cad1cee5320f52fd6de705f251ca |

来源revision未记录，不能声称固定wiki版本ID。缓存准备时间2026-10-29 23:57（Asia/Shanghai）。

构造变体只在测试内修改文本，不冒充真实公告。
测试负责选定板块，正式局部入口只接收正文、年份依据和真实起始行。

复现：`python -B -m pytest -q -p no:cacheprovider tests/test_公告局部识别.py tests/test_公告局部对照兼容.py`。

新情况的适配闭环：先保留原文/添加失败预期，再定位清理、阶段上下文、对象边界、日期或窗口检查；不使用活动名称特例让测试通过。已识别日期精确不等于角色已确认；未知情况应保留诊断而非生成伪确定记录。
