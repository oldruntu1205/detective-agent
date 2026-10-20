"""条件差异定位：把「两方吵起来了」拆成「两方说的不是同一件事」。

「说不准」这个终态最有价值的答案，往往不是「谁对谁错」，而是「他们各自加了什么限定条件」。

隔夜菜之争就是典型：
  A 方：「隔夜菜在**冷藏条件**下，亚硝酸盐含量通常低于国家限量标准，不会致癌」
  B 方：「**长期食用**会增加致癌风险，尤其是**室温放置超过 4 小时**的情况」
两句话都不算错，但都不是对同一句话的回答。把条件差异摆出来，比再给一个「说不准」有用得多。

实现上纯规则：条件词表 + 差集。不依赖模型，同一段文本永远抽出同一组条件。
条件词表可按领域包扩展（领域 JSON 里的 `conditions` 字段），例如财务领域会关心「口径（含税/不含税）」。
"""

from __future__ import annotations

from typing import Any

# 维度 → 词表。刻意控制在「会实质影响结论」的条件上，不收泛词。
CONDITION_DIMS: dict[str, list[str]] = {
    "人群": [
        "婴幼儿", "婴儿", "儿童", "小孩", "青少年", "学生",
        "孕妇", "哺乳期", "老年人", "老人", "成年人", "成人",
        "男性", "女性", "患者", "病人", "过敏体质", "特殊人群",
    ],
    "剂量与程度": [
        "长期", "短期", "少量", "微量", "大量", "过量", "适量",
        "偶尔", "频繁", "长期食用", "长期摄入", "长期使用",
        "高剂量", "低剂量", "超标", "超量",
    ],
    "使用场景": [
        "正常使用", "规范使用", "合规使用", "违规使用", "按说明使用",
        "高温", "低温", "常温", "室温", "冷藏", "冷冻", "密封", "开封",
        "加热", "反复加热", "空腹", "饭后", "餐前", "睡前",
        "室内", "室外", "密闭空间", "通风",
    ],
    "范围与口径": [
        "全部型号", "部分型号", "特定型号", "所有产品", "个别批次", "整批",
        "全额", "部分", "上限", "下限", "含税", "不含税", "口径一致", "口径不同",
    ],
    "地域": [
        "全国", "全省", "全市", "本省", "本市", "境内", "境外",
        "欧盟", "美国", "国际标准", "国家标准", "地方标准", "行业标准",
    ],
}

# 只有这些维度上的差异才算「实质条件差异」；单纯「全国 / 全省」不足以判定两方在说不同的事
SUBSTANTIVE = ("人群", "剂量与程度", "使用场景", "范围与口径")


def extract(text: str, extra: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    """抽出一段文本里的限定条件，按维度归组。"""
    table = CONDITION_DIMS
    if extra:
        merged: dict[str, list[str]] = {k: list(v) for k, v in CONDITION_DIMS.items()}
        for dim, words in extra.items():
            merged.setdefault(dim, [])
            merged[dim] = list(dict.fromkeys(merged[dim] + list(words)))
        table = merged
    found: dict[str, list[str]] = {}
    for dim, words in table.items():
        hit = [w for w in words if w in (text or "")]
        if hit:
            found[dim] = hit
    return found


def _dedupe(words: list[str]) -> list[str]:
    """「长期」和「长期食用」同时命中时只留长的那个，避免同一条件数两遍。"""
    return [w for w in words if not any(w != o and w in o for o in words)]


def _fmt(words: list[str], limit: int = 3) -> str:
    shown = "、".join(f"「{w}」" for w in words[:limit])
    if len(words) > limit:
        shown += f" 等 {len(words)} 项"
    return shown


def diff(a_text: str, b_text: str,
         extra: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """对比两段原话的限定条件，返回差异结构与一句可直接展示的说明。"""
    a = extract(a_text, extra)
    b = extract(b_text, extra)
    a_only: list[str] = []
    b_only: list[str] = []
    shared: list[str] = []
    differ_dims: set[str] = set()
    shared_dims: set[str] = set()

    for dim in set(a) | set(b):
        aw = set(a.get(dim, []))
        bw = set(b.get(dim, []))
        side_a = sorted(aw - bw)
        side_b = sorted(bw - aw)
        a_only += side_a
        b_only += side_b
        both = sorted(aw & bw)
        shared += both
        if both:
            shared_dims.add(dim)
        if (side_a or side_b) and dim in SUBSTANTIVE:
            differ_dims.add(dim)

    a_only = _dedupe(a_only)
    b_only = _dedupe(b_only)

    # 差异必须落在实质维度上，或差异项足够多，否则视为「条件其实一致」
    differ = bool(differ_dims) or (len(a_only) + len(b_only)) >= 3
    if not differ:
        return {
            "differ": False,
            "a_only": [], "b_only": [], "shared": shared,
            "dims": sorted(shared_dims),
            "note": "",
        }

    parts: list[str] = []
    if a_only:
        parts.append(f"一方限定在{_fmt(a_only)}")
    if b_only:
        parts.append(f"另一方限定在{_fmt(b_only)}")
    note = (
        "两方讨论的条件并不相同：" + "，".join(parts) + "。"
        "这更像两个不同条件下的两个结论，不宜按同一句话裁决——"
        "先确认你关心的是哪一种情形。"
    )
    return {
        "differ": True,
        "a_only": a_only,
        "b_only": b_only,
        "shared": shared,
        "dims": sorted(differ_dims),
        "note": note,
    }
