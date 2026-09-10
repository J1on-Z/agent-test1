"""RRF 混合检索测试：融合公式、去重、双路命中互惠提升。"""
from app.services.retrieval.hybrid import _rrf_fuse


def _hit(cid: str) -> dict:
    return {"chunk_id": cid, "content": f"content-{cid}", "meta": {}}


class TestRRF:
    def test_fuse_orders_by_rrf_score(self):
        vector = [(_hit("a"), 0.9), (_hit("b"), 0.8), (_hit("c"), 0.7)]
        bm25 = [(_hit("c"), 1.0), (_hit("d"), 0.9)]
        fused, scores = _rrf_fuse(vector, bm25)
        # c 双路都命中（rank1/rank3），互惠提升应排第一
        assert fused[0]["chunk_id"] == "c"
        assert set(scores) == {"a", "b", "c", "d"}

    def test_same_chunk_appears_once(self):
        vector = [(_hit("x"), 0.95), (_hit("y"), 0.5)]
        bm25 = [(_hit("x"), 1.0)]
        fused, _ = _rrf_fuse(vector, bm25)
        ids = [c["chunk_id"] for c in fused]
        assert ids.count("x") == 1
        assert len(ids) == 2

    def test_dual_hit_boosts_above_single_top(self):
        # 双路命中（即使非双路第一）的分数 > 单路第一的分数
        vector = [(_hit("a"), 0.99)]
        bm25 = [(_hit("b"), 1.0), (_hit("a"), 0.5)]
        fused, scores = _rrf_fuse(vector, bm25)
        assert fused[0]["chunk_id"] == "a"
        assert scores["a"] > scores["b"]

    def test_empty_inputs(self):
        fused, scores = _rrf_fuse([], [])
        assert fused == [] and scores == {}
