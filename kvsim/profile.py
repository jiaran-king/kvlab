"""Frozen A3 DSv4 continuous-state APC layout (MTP/CP disabled).

Source references and exclusions are in RULES.md. Block IDs share one pool;
bytes per ID are the sum of tensor buckets, NOT bytes per logical token.
"""

from dataclasses import asdict, dataclass

ASCEND_SHA = "3281a5fc44ec344ba304c9161a3959d8649471f4"
VLLM_SHA = "568afb3a13806beb53bb2e6bd518269357b237c0"


@dataclass(frozen=True)
class Group:
    name: str
    kind: str
    block: int
    window: int = 0
    ratio: int = 1
    layers: int = 0


def resolve(config):
    unknown = set(config) - {"profile", "block_size", "tp", "kv_bytes", "kv_gib", "retention", "max_input_tokens"}
    if unknown:
        raise NotImplementedError("Unsupported profile settings: " + ", ".join(sorted(unknown)))
    limit = config.get("max_input_tokens")
    if limit is not None and (type(limit) is not int or limit <= 0):
        raise ValueError("max_input_tokens must be a positive integer or null")
    b = config.get("block_size", 128)
    if b not in (32, 64, 128):
        raise NotImplementedError("A3 profile supports block_size 32, 64, 128 only")
    if config.get("profile", "ascend-a3-continuous") != "ascend-a3-continuous":
        raise NotImplementedError("Unknown runtime profile")
    if config.get("tp", 4) != 4:
        raise NotImplementedError("First profile fixes TP4; no arbitrary topology inference")
    budget = config.get("kv_bytes", int(config.get("kv_gib", 16) * 2**30))
    if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
        raise ValueError("KV budget must be a positive integer number of bytes per rank")
    # A3: C4 MLA BF16=512*2, indexer int8=128+FP16 scale.
    # 43 model layers: 21 C4, 20 C128, 43 SWA. No MTP layer.
    # _approximate_gcd([21,20,43,21,20], lower_bound=21) -> 22.
    # SWA is split into two groups (22/21). C4 KV and indexer states
    # form paired per-size buckets, padded to the canonical C4 page sizes.
    tuple_count = 22
    page_bytes = (1024 + 130) * b * tuple_count
    if budget < page_bytes:
        raise ValueError("KV budget cannot accommodate the reserved block")
    groups = [
        Group("C4-KV+index", "dense", b * 4, ratio=4, layers=21),
        Group("C128-KV", "dense", b * 128, ratio=128, layers=20),
        Group("SWA-0", "window", b, 128, layers=22),
        Group("SWA-1", "window", b, 128, layers=21),
        Group("C4-state+index-state", "window", b // 16, 8, layers=21),
        Group("C128-state", "window", b // 4, 128, layers=20),
    ]
    retention = config.get("retention", b * 128)
    if retention != b * 128:
        raise NotImplementedError("First preset supports retention=128*block_size only")
    return {
        "name": "DeepSeek-V4 Flash · A3 · continuous state · TP4",
        "ascend_commit": ASCEND_SHA, "vllm_commit": VLLM_SHA,
        "profile": "ascend-a3-continuous", "block_size": b,
        "alignment": b * 128, "hash_block_size": b // 16,
        "retention": retention, "tp": 4, "kv_bytes": budget,
        "page_bytes_per_rank": page_bytes, "num_blocks": budget // page_bytes,
        "reserved_blocks": 1, "groups": [asdict(g) for g in groups],
        "scope": "Source-derived frozen preset; historical Ascend local patches and exact runtime layout not supplied. Not a hardware-fit prediction.",
    }
