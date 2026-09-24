"""Reconstruct the captured v3.1 Ascend hybrid KV layout for the native core.

The physical block size is derived from all captured KV tensors. This module
only constructs vLLM configuration objects; cache lookup/allocation remain in
the target vLLM and vllm-ascend implementations.
"""
from __future__ import annotations

import json
from pathlib import Path

LAYOUT_FILE = Path(__file__).with_name('ascend-v31-layout.json')
EXPECTED_BLOCKS = {10: 13216, 16: 21146, 24: 31719}


def captured_layout() -> dict:
    layout = json.loads(LAYOUT_FILE.read_text())
    if layout['schema'] != 'kvlab-ascend-v31-layout/v1':
        raise ValueError('unsupported Ascend layout schema')
    if (layout['scheduler_block_size'], layout['hash_block_size'],
        layout['lcm_block_size'], layout['retention_interval'],
        layout['hit_alignment']) != (32, 2, 4096, 4096, 32):
        raise ValueError('captured Ascend scheduler or recovery layout drift')
    if len(layout['kv_cache_groups']) != 6 or len(layout['kv_cache_tensors']) != 44:
        raise ValueError('captured Ascend cache group/tensor count drift')
    total = sum(row['bytes_per_block'] for row in layout['kv_cache_tensors'])
    if total != layout['bytes_per_physical_block'] or total != 812416:
        raise ValueError('captured Ascend per-block bytes drift')
    if any(row['bytes_per_block'] <= 0 or row['block_stride'] != 0
           for row in layout['kv_cache_tensors']):
        raise ValueError('invalid Ascend tensor size or block stride')
    for gib, expected in EXPECTED_BLOCKS.items():
        if gib * (1024**3) // total != expected:
            raise ValueError(f'{gib} GiB block count differs from captured run')
    return layout


def blocks_for_budget_gib(gib: int) -> int:
    if type(gib) is not int or gib < 1:
        raise ValueError('Ascend budget GiB must be a positive integer')
    return gib * (1024**3) // captured_layout()['bytes_per_physical_block']


def make_native_cache_config(num_blocks: int):
    """Build real KVCacheConfig with target Ascend spec classes, no cache emulation."""
    if type(num_blocks) is not int or num_blocks < 1:
        raise ValueError('num_blocks must be a positive integer')
    import torch
    from vllm.v1.kv_cache_interface import KVCacheConfig, KVCacheGroupSpec, KVCacheTensor, KVQuantMode
    from vllm_ascend.core.kv_cache_interface import AscendMLAAttentionSpec, AscendSlidingWindowMLASpec

    layout = captured_layout()
    dtypes = {f'torch.{name}': getattr(torch, name) for name in
              ('int8', 'bfloat16', 'float32', 'float16')}
    groups = []
    for index, entry in enumerate(layout['kv_cache_groups']):
        fields = dict(entry['kv_cache_spec'])
        for key in ('dtype', 'scale_dtype'):
            if key in fields:
                fields[key] = dtypes[fields[key]]
        fields['kv_quant_mode'] = KVQuantMode(fields['kv_quant_mode'])
        spec_cls = AscendMLAAttentionSpec if index < 2 else AscendSlidingWindowMLASpec
        spec = spec_cls(**fields)
        if spec.block_size != entry['kv_cache_spec']['block_size']:
            raise ValueError(f'Ascend group {index} block size changed in native spec')
        groups.append(KVCacheGroupSpec(layer_names=entry['layer_names'],
                                       kv_cache_spec=spec,
                                       is_eagle_group=entry['is_eagle_group']))
    tensors = [KVCacheTensor(size=num_blocks * row['bytes_per_block'],
                             shared_by=row['shared_by'], offset=row['offset'],
                             block_stride=row['block_stride'])
               for row in layout['kv_cache_tensors']]
    return KVCacheConfig(num_blocks=num_blocks,
                         kv_cache_tensors=tensors, kv_cache_groups=groups)
