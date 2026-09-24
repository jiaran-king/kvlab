# Ascend v3.1 四 P／4K 对账资产

此目录保存已授权公开的最终 v3.1 数据：1,313 条冻结请求、10／16／24 GiB 三档 P 侧模拟与实测逐请求证据，以及独立 16 GiB 重复轮。真实请求 token 与会话标识已包含在文件中。

- `frozen-bodies.tar.gz`：捕获时的 1,313 份原始输入正文和对应 token 文件，连同冻结 manifest。解压后目录名为 `calibration-frozen-v31`。
- `prepared/`：校验并规范化后的 P 输入 token、四份每 P 请求流、路由及实测参考。P 输入比客户端输入每请求少一个末尾 `128822`；原生查询仍包含它。
- `measurements/{run}/`：四轮各自选取的原始 P engine event、审计、路由、指标快照、冻结 manifest、运行身份和 replay 计划。`archive-index.json` 属于更大的原始运行归档，本目录只保留本次复算必需的选取文件。
- `results/`：三档 × 四 P 的 12 份原生离线模拟逐请求输出。
- `v31-native-comparison.json`：每档全局、各 P、逐请求的实测值、模拟值和差额，以及容量增益请求集合对照。`summary.json` 是不含 token／请求 ID 的汇总视图。

从仓库根目录运行后处理校验：

```sh
sha256sum -c validation/ascend-v31/SHA256SUMS
python3 -m kvsim.native.compare_ascend_v31 \
  --prepared validation/ascend-v31/prepared \
  --results validation/ascend-v31/results \
  --output /tmp/v31-native-comparison.json
cmp /tmp/v31-native-comparison.json validation/ascend-v31/v31-native-comparison.json
```

从原始捕获重新生成准备文件与实测参考：

```sh
mkdir -p /tmp/kvlab-v31-capture /tmp/kvlab-v31-prepared
tar -C /tmp/kvlab-v31-capture -xzf validation/ascend-v31/frozen-bodies.tar.gz
python3 scripts/prepare_ascend_v31.py \
  --plan validation/ascend-v31/measurements/cal16-v31-0924-01/replay/replay-plan.json \
  --archive-root validation/ascend-v31/measurements \
  --bodies-dir /tmp/kvlab-v31-capture/calibration-frozen-v31 \
  --output-dir /tmp/kvlab-v31-prepared
python3 scripts/prepare_ascend_v31_reference.py \
  --archive-root validation/ascend-v31/measurements \
  --output /tmp/kvlab-v31-prepared/v31-measured-reference.json
```

重新生成的 `v31-engine-workload.json.gz` SHA256 应为 `e5ba54f2ec69dc8544b6cbd52a80fee635004600af1fb986963ca9dda52c6641`；`v31-measured-reference.json` 应为 `87c27fb78a078145bf96edf75641b3d4c88826a4f4e649ce948d2c38ccf0501d`。其余每 P 输入与路由也应与 `prepared/` 中的文件逐字节相同。

重新运行 `results/` 中的原生模拟需要 `START_HERE.md` 所述锁定 vLLM／vllm-ascend Python 环境。上述准备与对账只需 Python 标准库，不加载模型或 NPU。所选档位各 1,313 条请求均逐条零差额；这不扩展为其他 Ascend 配置或 AFD／non-AFD 显存收益的验证。
