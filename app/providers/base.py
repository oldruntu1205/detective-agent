"""检索层接口。真实实现见 tencent_wsa.py，离线样例见 mock.py。"""

from __future__ import annotations

from ..models import SearchHit


class SearchError(RuntimeError):
    """检索层失败。上层必须如实报错，不允许静默编造结果。"""


class Provider:
    name = "base"

    def search(self, query: str, domain: str = "") -> list[SearchHit]:  # pragma: no cover - 接口定义
        """domain 只对离线样例有意义（按领域挑样例），真实检索层忽略它。"""
        raise NotImplementedError
