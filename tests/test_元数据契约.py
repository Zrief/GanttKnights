"""上架契约：`metadata.yaml` 的字段形状、平台白名单、版本三处一致。

为什么值得测（§8「配置即契约」的同一思路，换个文件）：
- `metadata.yaml` 是**市场记录的唯一来源**——市场 CI 会拿它的 `author`/`name`/`version`
  与发布记录逐字比对（[市场 JSON 规范 2026-06-27](https://docs.astrbot.app/dev/plugin-market/2026-06-27.html) 第 11 节），
  拼错一个 `support_platforms` 取值市场不会报错，只会让卡片上多一个点不亮的平台；
- `version` 在本仓有**三份拷贝**（metadata / `main.py` 的 插件版本 / `pyproject.toml`），
  帮助页显示的是 `main.py` 那份——漂了就会出现"帮助里写 0.1.0、市场显示 0.2.0"；
- AstrBot 侧的解析器只要求 `name`/`desc`/`version`/`author` 是非空字符串
  （`core/star/updater.py:335`），**其余字段写错它一声不响**，所以形状得自己钉。

只依赖标准库 + `pytest`；PyYAML 用 `importorskip`（AstrBot 环境自带，裸环境跳过而不是报错）。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="读 metadata.yaml 需要 PyYAML（AstrBot 环境自带）")

仓库根 = Path(__file__).resolve().parent.parent

# 官方「声明支持平台」文档列出的全部合法取值（2026-09-14 核对 docs.astrbot.app/dev/star/plugin-new.html，
# 与 4.28 源码 astrbot/core/platform/sources/ 下注册的适配器名一致；旧文档只列 14 个，别照抄）。
平台白名单 = {
    "aiocqhttp", "qq_official", "qq_official_webhook", "telegram", "wecom", "wecom_ai_bot",
    "lark", "dingtalk", "discord", "slack", "kook", "vocechat", "weixin_official_account",
    "weixin_oc", "satori", "misskey", "line", "matrix", "mattermost",
}

# 本插件**不该**声明的平台：它们发不出"本地生成的图片长图"这件事本身就有硬限制。
# 声明支持平台只是给市场卡片看的（AstrBot 不据此拦安装），所以宁可少写。
硬限制 = {
    "line": "图片必须能解析成公网 https URL（platform/sources/line/line_event.py 的 _resolve_image_url）",
    "weixin_official_account": "客服消息只有 48 小时窗口，定时推送到点几乎必然过期",
}


@pytest.fixture(scope="module")
def 元数据() -> dict:
    return yaml.safe_load((仓库根 / "metadata.yaml").read_text(encoding="utf-8"))


def test_必填字段非空且形状正确(元数据):
    for 字段 in ("name", "display_name", "short_desc", "desc", "version", "author", "repo"):
        assert isinstance(元数据.get(字段), str), f"{字段} 必须是字符串"
        assert 元数据[字段].strip(), f"{字段} 不能为空"
    assert re.fullmatch(r"astrbot_plugin_[a-z0-9_]+", 元数据["name"]), "插件名规范：全小写 + astrbot_plugin_ 前缀"
    assert 元数据["name"].isidentifier(), "宿主按包名 __import__，name 必须是合法 Python 标识符"
    assert "/" not in 元数据["author"] and "/" not in 元数据["name"], "author/name 不得含 /（身份是 author/name）"


def test_repo_是合规的_GitHub_仓库地址(元数据):
    # 市场规范 7.1：只能是 https://github.com/{owner}/{repo}[.git|/tree/{branch}]
    形状 = r"https://github\.com/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+(?:\.git|/tree/[A-Za-z0-9_-]+)?"
    assert re.fullmatch(形状, 元数据["repo"]), f"repo 形状不合规：{元数据['repo']}"


def test_短描述适合市场卡片(元数据):
    短 = 元数据["short_desc"]
    assert "\n" not in 短, "short_desc 是卡片上的一行，不要换行"
    assert len(短) <= 60, f"short_desc 太长（{len(短)} 字），卡片会截断"


def test_详述写明游戏与数据来源(元数据):
    """README 的致谢同款要求搬到 desc：数据来自 PRTS 就得写出来。"""
    详 = 元数据["desc"]
    assert "明日方舟" in 详 and "PRTS" in 详, "desc 里应写清这是什么游戏、数据来自哪里"


def test_平台声明在白名单内且避开有硬限制的平台(元数据):
    声明 = 元数据.get("support_platforms")
    assert isinstance(声明, list) and 声明, "support_platforms 应该是非空列表（规范第 15 条：字符串数组）"
    assert all(isinstance(x, str) and x.strip() for x in 声明), 声明
    assert len(set(声明)) == len(声明), f"有重复：{声明}"
    assert set(声明) <= 平台白名单, f"不在官方白名单里：{sorted(set(声明) - 平台白名单)}"
    assert not (set(声明) & set(硬限制)), (
        f"声明了发不出本地图片的平台：{[(p, 硬限制[p]) for p in 声明 if p in 硬限制]}"
    )


def test_tags_形状正确(元数据):
    标签 = 元数据.get("tags")
    assert isinstance(标签, list) and 标签, "tags 应该是非空列表"
    assert all(isinstance(x, str) and x.strip() for x in 标签), 标签
    assert len(set(标签)) == len(标签), f"有重复：{标签}"
    assert len(标签) <= 10, f"标签过多（{len(标签)} 个）——市场里多数插件写 1~3 个"


def test_tags_给游戏名与产物类型各留一个英文入口(元数据):
    """市场检索按标签字面匹配，同一件事的中英文是两个检索入口（§18.4）。

    只给"游戏名 + 产物类型"配英文；`游戏/图片/推送` 这类通用词不配（配上只是稀释信息量）。
    """
    标签 = set(元数据["tags"])
    for 中文, 英文 in (("明日方舟", "arknights"), ("甘特图", "gantt")):
        assert 中文 in 标签, f"缺中文标签 {中文}"
        assert 英文 in 标签, f"缺对应的英文标签 {英文}（{中文} 的检索入口）"


def test_astrbot_版本表达式合法且包含_4_17(元数据):
    from packaging.specifiers import SpecifierSet   # pytest 的依赖，必然存在

    值 = 元数据["astrbot_version"]
    assert not 值.startswith("v"), "官方要求不加 v 前缀"
    限定 = SpecifierSet(值)
    assert 限定.contains("4.17.0"), (
        "4.17.0 是逐项核对源码后定的下限（send_message(umo, chain) / register_command(alias=set) / "
        "permission_type / get_astrbot_data_path / astrbot.api 导出 AstrBotConfig 都在 4.17.0 里）"
    )


def test_版本三处一致(元数据):
    """metadata.yaml / main.py 的 插件版本 / pyproject.toml 必须是同一个版本号。"""
    源码 = (仓库根 / "main.py").read_text(encoding="utf-8")
    匹配 = re.search(r'^插件版本\s*=\s*"([^"]+)"', 源码, re.MULTILINE)
    assert 匹配, "main.py 里找不到 插件版本 常量"
    项目 = tomllib.loads((仓库根 / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]

    版本 = 元数据["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", 版本), f"版本号应遵循语义化版本：{版本}"
    assert 匹配.group(1) == 版本, f"main.py 的 插件版本={匹配.group(1)}，metadata 是 {版本}"
    assert 项目 == 版本, f"pyproject 的 version={项目}，metadata 是 {版本}"
