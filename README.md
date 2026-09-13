# GanttKnights
针对游戏明日方舟特化的甘特图绘图工具，基于matplotlib | A Gantt chart plotting tool specialized for the mobile game "Arknights", developed using matplotlib.

效果展示
![效果展示](./Gantt.jpg)

## 使用

```bash
uv sync          # 或 pip install httpx matplotlib pandas Pillow numpy

python main.py                       # 生成 Gantt.jpg（数据每天只爬一次）
python main.py --force               # 强制重新爬取
python main.py --bootstrap --force   # 数据初次建立：回溯已结束活动的公告，补录剿灭/保全等长期任务
python prts_scraper.py               # 只爬取活动数据并在控制台打印
```

数据全部来自 [PRTS Wiki](https://prts.wiki)：SMW ask 查活动时间、卡池一览与活动公告的 wikitext 解析卡池和子活动，需要网络。

## 版面

一张图从上到下三段，全部按像素排布（`src/绘图_排版.py`，dpi150 下 1 数据单位 = 1 像素）：

- **页眉**：大字衬线标题 + 右侧"数据来源 / 更新时间"块；
- **甘特图**：固定宽左信息列（类型色条 + 关键词）+ 顶部日期轴带 + 每日竖网格 + TODAY 柱带；
  事件名优先写在条上，条太短时用细箭头引到条外；
- **底栏**：凭证兑换 / 新增时装 / 新增模组 三区卡片（圆角头像 + 干员名 + 模组名），
  行数与格宽由试排搜索决定：行数最少 → 填得最满 → 格宽最接近理想值。

配色不写死：整套色值由随机选中的背景图推导（`src/绘图_主题.py`），推导规则见 [配色规范.md](./配色规范.md)。

可选素材：`背景图/` 放任意背景图（每次随机取一张，整套色系由它推导）；字体 `字体/NotoSansCJKsc-Regular.otf` 等静态字重不在仓库里，缺失时会回退到系统中文字体。
