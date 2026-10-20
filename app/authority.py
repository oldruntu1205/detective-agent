"""信源权威度分级。

两个信号叠加：
1. 元宝搜索旗舰版直接返回的 authority_level（0~5，越大越权威）
2. 域名白名单分级（不依赖版本，标准版/极速版也能用）

最终 tier 越小越权威：
  T1 权威一手（政府 / 部委 / 学术 / 央媒）
  T2 主流媒体
  T3 垂直机构 / 专业站 / 平台官方文档
  T4 UGC 与未知站点
"""

from __future__ import annotations

from urllib.parse import urlparse

TIER_LABEL = {
    1: "T1 权威一手",
    2: "T2 主流媒体",
    3: "T3 垂直专业",
    4: "T4 UGC / 未知",
}

TIER_WEIGHT = {1: 1.0, 2: 0.7, 3: 0.5, 4: 0.25}

# 只匹配域名后缀，避免 "gov.cn.xxx.com" 这类伪造
T1_DOMAINS = (
    "gov.cn", "cac.gov.cn", "nhc.gov.cn", "samr.gov.cn", "most.gov.cn",
    "moa.gov.cn", "moe.gov.cn", "mps.gov.cn", "stats.gov.cn", "court.gov.cn",
    "edu.cn", "ac.cn", "cas.cn", "cae.cn",
    "who.int", "un.org", "nature.com", "science.org", "thelancet.com",
    "nejm.org", "bmj.com", "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov",
    "cnki.net", "wanfangdata.com.cn", "arxiv.org",
    "xinhuanet.com", "news.cn", "people.com.cn", "cctv.com", "cnr.cn", "cgtn.com",
    "piyao.org.cn", "kepuchina.cn", "cast.org.cn",
    "cloud.tencent.com", "docs.qq.com",
)

T2_DOMAINS = (
    "thepaper.cn", "caixin.com", "yicai.com", "jiemian.com", "stcn.com",
    "cls.cn", "21jingji.com", "eeo.com.cn", "chinanews.com.cn", "china.com.cn",
    "gmw.cn", "ce.cn", "cyol.com", "bjnews.com.cn", "nfnews.com",
    "sina.com.cn", "163.com", "qq.com", "ifeng.com", "sohu.com",
    "36kr.com", "huxiu.com", "tmtpost.com", "geekpark.net", "sspai.com",
    "toutiao.com", "douban.com", "v.qq.com", "iqiyi.com", "youku.com",
    "mgtv.com", "bilibili.com",
)

T3_DOMAINS = (
    "dxy.cn", "guokr.com", "msdmanuals.cn", "yiigle.com", "medsci.cn",
    "baike.baidu.com", "wikipedia.org", "csdn.net", "juejin.cn",
    "github.com", "gitee.com", "docs.python.org", "developer.mozilla.org",
    "sspai.com.cn", "zhangyue.com", "weread.qq.com",
)

T4_HINT = (
    "weibo.com", "xiaohongshu.com", "douyin.com", "kuaishou.com", "tieba.baidu.com",
    "mp.weixin.qq.com", "jianshu.com", "360doc.com", "baijiahao.baidu.com",
    "zhihu.com", "bilibili.com", "xueqiu.com",
)


def domain_of(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower().strip(".")
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _endswith_any(domain: str, suffixes: tuple[str, ...]) -> bool:
    return any(domain == s or domain.endswith("." + s) for s in suffixes)


def classify(url: str, site: str = "", authority_level: int | None = None,
             extra_tiers: dict[str, int] | None = None) -> tuple[str, int, str]:
    """返回 (domain, tier, tier_label)。

    extra_tiers 来自领域包，优先级高于内置白名单：同一站点在不同行业里分量不同
    （比如 1688 在通用场景算 UGC，在招投标场景更是「待核实主张」）。
    """
    domain = domain_of(url)

    tier: int | None = None
    if domain and extra_tiers:
        # 取最长后缀匹配，避免 .gov.cn 的通配吃掉 specific 子域规则
        matched = [s for s in extra_tiers if domain == s or domain.endswith("." + s)]
        if matched:
            tier = extra_tiers[max(matched, key=len)]

    if tier is None and domain:
        if _endswith_any(domain, T4_HINT):
            tier = 4
        elif _endswith_any(domain, T1_DOMAINS):
            tier = 1
        elif _endswith_any(domain, T2_DOMAINS):
            tier = 2
        elif _endswith_any(domain, T3_DOMAINS):
            tier = 3
        else:
            tier = 4

    # 接口自带权威度用于校正：旗舰版返回 0~5
    if authority_level is not None:
        by_api = 1 if authority_level >= 4 else 2 if authority_level >= 3 else 3 if authority_level >= 2 else 4
        if tier is None:
            tier = by_api
        elif tier == 4 and by_api < 4:
            # 白名单没覆盖，但接口说它权威 → 采信接口
            tier = by_api
        elif tier > by_api:
            # 接口认为比白名单更权威时，取更权威的一档，但不越过 T1
            tier = max(1, min(tier, by_api))

    tier = tier or 4
    return domain, tier, TIER_LABEL[tier]


def tier_weight(tier: int) -> float:
    return TIER_WEIGHT.get(tier, 0.25)
