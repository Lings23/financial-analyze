# Phase 2 验收与修复（2026-10-02）

## 结论与范围

**固定、有界、单股概览 Single 首版验收通过；Phase 2 的广泛真实模型任务质量整体验收仍未完成。** 本轮按 PLAN 的 P2.1–P2.6 检查实现、复现缺陷、修复并复测。没有进入 Phase 3–6，没有新增模型调用、金融 Provider 调用或修改真实快照。一次历史真实模型联调仍仅证明该次配置端点/指定模型的严格选择与回放。

真实冻结任务集对当前固定 Runtime 的任务通过率为 50/50，独立算术 248/248，Claim 血缘 248/248；达到该限定任务集的 95% / 99% / 100% 门槛。这是已有真实输入上的离线固定请求评测，不是新供应商质量认证、盲样持出集、自然语言任务成功率或真实模型重点质量认证；全局门槛不得由此泛化。

## 已复现的不通过项与修复

| 不通过项 | 修复 | 回归证据 |
|---|---|---|
| 模型 JSON 重复 highlights 键被最后一个值覆盖，非法前值也可进入 verified | 使用拒绝重复键的 JSON 解码 | 修复前新测试失败，修复后通过 |
| Runtime 仅检查 Token 合计，未自行拒绝负数、bool、浮点计数或超 output_tokens 输出 | Runtime 独立检查每个计数为非负 int、合计和预留上限、输出预算 | 四种异常用量均拒绝，保留失败尝试与预留 |
| 恢复未完成任务时，源重读不检查原绝对 deadline；已计算缓存也可能在超时后生成报告 | 在未完成恢复的每次源重读前后检查 deadline/取消；未完成重授权不发布缓存事实；pending 结果保持 unknown_outcome_no_replay | 过期恢复零源查询、迟到重读零事实、Token 预留保留、模型不重发；已完成授权回放跨 deadline 仍通过 |

修改：`src/stock_research/research/runtime.py`，新增五项 `tests/test_research.py` 测试。原三项失败日志 `.runtime/phase2-acceptance-defects-before.log` 保留，没有覆盖旧验收报告。

## 本轮实际执行

| 检查 | 结果与证据 |
|---|---|
| 初始系统 Python 离线基线 | 157 项：144 通过、13 跳过（12 数据库、1 可选 AKShare SDK）；`.runtime/phase2-acceptance-offline.log` |
| 初始项目 .venv 隔离 PostgreSQL | 157/157，0 跳过；`.runtime/phase2-acceptance-postgres-baseline.log` |
| 修复后项目 .venv 离线全量 | **162 项：150 通过、12 数据库跳过**；`.runtime/phase2-acceptance-offline-final.log` |
| 修复后项目 .venv 隔离 PostgreSQL | **162/162，0 跳过**；`.runtime/phase2-acceptance-postgres-final.log` |
| 原冻结合成评测重新执行 | **20/20 任务，70/70 算术，130/130 血缘**；`.artifacts/phase2/acceptance-20261002/synthetic.json`。fixture 模型，不是真实金融真值 |
| 新真实冻结任务集 | **50/50 任务、248/248 算术与 Claim 血缘、563 Evidence**；`.artifacts/phase2/acceptance-20261002/real-final/result.json`，逐任务报告同目录 |
| 每个真实任务的恢复/权限/PIT | 50 次新 CheckpointStore 实例回放一致；50 次撤销 Tushare 来源拒绝；50 次采集前 cutoff 无事实。真实模型及金融 Provider 调用均为 0 |
| 新真实冻结集再次执行 | 增加逐数值正确计数后重新执行 **50/50、248/248、563 Evidence**，结果保持；`.artifacts/phase2/acceptance-20261002/real-retest/result.json`，`.runtime/phase2-acceptance-real-retest.log` |
| 编译/依赖/发行与密钥排除 | compileall、pip check 通过；sdist 46 文件含全部 8 个 research 模块，不包含本地凭据/.runtime/.artifacts；484 个文件及包内精确凭据匹配均 0。`.artifacts/phase2/acceptance-20261002/distribution-secret-check.json`；wheel 本轮未验证 |

测试数据库只使用随机命名的临时容器与 localhost 随机端口，测试后清理；持久验收库为只读查询，没有执行迁移、采集或删除。首次沙箱 Docker 管道权限不足，获得工具自动审批后执行隔离测试通过；不是业务测试失败。初版新评测脚本错误地使用空 provider 权限集合，被 AccessContext 合法拒绝；改为仅允许 cninfo 来验证 Tushare 撤权，原失败日志及目录保留。

## 新真实任务集的独立性与分母

`evaluation/phase2_real_acceptance_20261002.json` 固定 25 股 × 两行情窗口，与原 P1.7 正式采样相同；不筛除停牌、新上市、北交所或缺失项。输入为已保存的 75 次请求快照；每个任务固定市场快照、利润快照、证券、窗口、system cutoff 和来源。缺行只计算已观察区间，缺指标按明确期望产生 partial，coverage 始终 not_verified。

冻结 corpus SHA-256：`ce801f30b5ef8a1fe33711c8d27df6549f6e248fb031aefffce0caf897e00d7d`。在 Runtime 执行前，由独立 Fraction oracle 生成预期分数，锁定原采样 plan/run 字节哈希及每任务授权输入内容哈希；没有调用生产 calculate 生成答案。算术包含首末价格变化、观察收盘回撤、最新可见利润表值及存在正基数时同比。检查完整事实集合、预期 completed/partial、血缘、来源单位、Provider 调用引用、附件列表、原快照与 public/system 时间约束。

本轮使用已有金融原始值验证 Runtime 的正确转换与计算，不复核所有原文金融真值；P1.7 已有量额差异、缺独立财务口径和各阶段分母保留。50 个任务是固定 market/income 切片；其他域由已有扩展与合成工具测试覆盖，不能据此声称所有域都完成独立真实端到端任务认证。50 个主任务之外的恢复/撤权/PIT 检查不加入任务成功率分母。

运行（原数据库和 Artifact 必须存在，输出目录必须为新目录）：

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
& ./scripts/test-postgres.ps1 -Image 57c72fd2a128
.\.venv\Scripts\python.exe scripts/accept_phase2_real.py --output .artifacts/phase2/new-real-acceptance
```

`--prepare` 只用于创建新的冻结 corpus，默认 corpus 已存在时拒绝覆盖。默认评测不重新生成答案。脚本读取项目原有本地 DSN，从不打印、复制或保存凭据；注册表为空、executor/model 为 None，不可能触发金融 Provider/模型网络派发。

## 尚未认证

广泛独立真实 L1/L2 模型任务成功率、模型重点选择质量与持续服务表现仍未评测。先前批准仅限既有五条事实的一次模型请求，本轮没有扩大外发。自然语言解析、动态工具循环不在已授权固定首版必需范围。上述缺口是验收证据边界，不作为已修复缺陷或已通过测试记载。
