# KVLab

用于分析 KV Cache 容量、前缀复用与本地输入处理量的离线实验工具。当前正式后端复用锁定版本的原生 vLLM Scheduler 和缓存管理器，通过 CPU 逻辑推进，不运行模型张量计算。

## 当前入口

- [START_HERE.md](START_HERE.md)：CLI、输入格式、Agent 使用顺序、环境与测试命令。
- [ACCEPTANCE.md](ACCEPTANCE.md)：最新 F1–F5 修复及独立 Agent 演练验收。
- [ASCEND_V31_REPORT.md](ASCEND_V31_REPORT.md)：当前 Ascend v3.1 四 P／4K 原生对账结论。
- [CURRENT_GOAL.md](CURRENT_GOAL.md)：上一阶段的可靠性与 Agent 使用目标。
- [`kvsim/native`](kvsim/native)：正式原生离线驱动、比较器和证据工具。
- [`kvsim/tests/fixtures`](kvsim/tests/fixtures)：可独立运行回归的小型样例。
- [`kvsim/KVLab.html`](kvsim/KVLab.html)：保留的可选结果页；HTML 暂缓，不是 CLI 的必经步骤。
- [`kvsim/source`](kvsim/source)：已有 vLLM / Ascend 机制源码参考；保留上游许可证。

当前验证的配置包括 H20 DeepSeek-V4 TP2 五组布局，以及最终 v3.1 Ascend 四 P／4K 恢复布局。Ascend 入口使用目标原生异步 Scheduler 和缓存协调器；10／16／24 GiB 三档的 3,939 条请求在实际采用、原生查询／命中和 local-compute 上与归档实测逐条一致。主结果为实际前缀采用比例、原生查询命中率和累计 local-compute。

AFD／non-AFD 的实际显存账本尚未接入；不把当前结果解释为 TTFT、吞吐或 AFD 收益。Ascend 支持限于已验证的 v3.1 配置。根目录其他 Goal/REPORT/STATUS 和 stage-v2…stage-v6 是历史材料，以 ASCEND_V31_REPORT、START_HERE 和 ACCEPTANCE 为当前入口。

## 完整项目与历史数据

本仓库不是只上传精简交付包：Git 包含当前和历史相关源码、前端、测试、配置、文档。完整工作区快照在 [Release full-project-20260924](https://github.com/jiaran-king/kvlab/releases/tag/full-project-20260924)，包括所有历史实验输入、原始日志、结果、76/425 请求相关资产、历次交付包、Ascend 交接材料及运行时源码证据。

[GitHub 普通 Git 文件限制](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)不适合本项目的大型原始日志，因此大数据存放在 Release 附件中；`git clone` 本身不会下载这些附件。

```sh
gh repo clone jiaran-king/kvlab
cd kvlab
gh release download full-project-20260924 --repo jiaran-king/kvlab \
  --pattern 'KVLab_full_project_20260924.tar.gz' --pattern SHA256SUMS --dir ../kvlab-snapshot
cd ../kvlab-snapshot
shasum -a 256 -c SHA256SUMS
tar -xzf KVLab_full_project_20260924.tar.gz
```

解压产生完整历史目录 `KVLab_full_project_20260924/`。文件清单与排除项见 [`FULL_PROJECT_MANIFEST.json`](FULL_PROJECT_MANIFEST.json)。快照保留原工作区相对路径；引用工作区历史资产的旧测试可在该快照中检查，当前 CLI 回归不需要下载大数据。

排除项仅为：本地 `.git` 元数据、虚拟环境/依赖安装目录、缓存、临时渲染目录，以及与 KVLab 无关的 `codex-startup-fix`。原生运行时二进制、模型权重和服务器本机状态不在本地项目中，本仓库不冒充可直接重建整台服务器的备份。

## 测试

```sh
python3 -m unittest discover -s kvsim/tests -p 'test_native*.py' -v
```

Replay 导出测试需 Python 3.12 及 `kvsim/requirements-export.txt` 依赖，见 START_HERE。原生运行仍需要锁定的补丁 vLLM CPU 环境，并遵守服务器调度和资源规则；不要在登录节点运行实验。

## 第三方代码

保留各上游源码目录附带的 LICENSE、版权头及版本来源记录。本次上传没有替项目自行选择新的整体开源许可证。当前仓库为公开仓库；本轮捕获的完整请求 token 和逐请求证据未提交到 Git。
