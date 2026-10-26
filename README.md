# MemRSI_backup

PAOS / LIBERO / G–U memory and RSI research backup, exported on 2026-10-26.

This is an archival research snapshot, **not evidence that RSI is effective**. It preserves earlier versions, rejected candidates, method failures, physical execution failures, and cost limitations.

## 内容 / Contents

- `archive/local-work/`: method implementations, controllers, offline tests, audits and experiment preparation.
- `archive/node107/`, `archive/node108/`: frozen code, policies, registrations, budgets and per-run result summaries.
- `archive/old-server/`, `archive/dependencies/`: selected earlier research and custom runtime source.
- `EXPORT-MANIFEST.json`: export coverage and intentional omissions.
- `SECRET-SCAN.json`: public-export credential scan summary (no secret values).
- `DATA-SHA256.json`: checksums for downloadable data artifacts.
- `restore_data.py`: verify and reconstruct the archived experimental records.

完整的公开实验记录、模型调用轨迹、记忆快照、视频、图像和状态数组放在 [Hugging Face dataset](https://huggingface.co/datasets/cherishing/MemRSI_backup)。GitHub 主要保留可浏览的代码与结果摘要。相同内容按 SHA-256 去重；数据集的 `file-index.jsonl.gz` 保留原始目录映射。

## 当前研究状态

最后一次固定时钟的三策略训练开发比较完成 24/24 回放：parent 7/22、old_joint 12/22、latest_joint 4/22 个正确计分点；完整完成数均为 0。old_joint 通过该轮预登记开发门槛，仅获得后续 pilot 资格，**不等于独立物理评估成功或 RSI 有效**。旧版本失败和先前保留条件退化仍然保留。100 条件扩展尚未启动。

部分调用成本不完整，tokens 是下界，不能把 unknown requests 当零。回放成绩不能冒充物理任务成功；跨版本成绩不是重复独立样本。

## 获取与校验数据

1. 从上述 Hugging Face 页面下载 `text-objects.tar.gz`、`media-objects.tar.gz`、`file-index.jsonl.gz` 和 `DATA-SHA256.json` 至同一目录。
2. 运行 `python restore_data.py --data-dir /path/to/downloads --output /path/to/restored`。
3. 仅需文本时可加 `--text-only`，无需下载媒体归档。恢复脚本核验归档和每个文件的 SHA-256，并拒绝覆盖不同内容的已有文件。

公开导出删除了密钥、令牌、机器连接配置以及不适合公开的运行控制信息。原始与公开 SHA-256 同时记录；实验登记中原有哈希仍指向原字节。原始本地备份保持不变。

大型可重新获取的公共模型权重、Conda 环境、安装包、缓存、嵌套机器归档及不完整下载未上传。这里不是可直接启动的虚拟机镜像。历史脚本含原机器路径与依赖，迁移时须重新配置；不要直接执行旧的 launch/stage/pipeline 脚本，否则可能重复提交实验。所有原研究语言模型调用约束为经本机 19098 网关。

## Rights and provenance

This repository does not grant a new blanket license to third-party source, data or assets. Existing notices and licenses continue to apply. Reconstructible upstream dependency installations and model weights are intentionally excluded. Use the frozen registrations, source hashes and original license notices when tracing provenance.
