# 2026-10-12 更新汇总

本次整理范围为上次远端提交 `f5cf776`（2026-10-06）之后的本地源码、测试、验收脚本和设计文档。只进行离线检查及仓库同步，不启动新的模型请求、金融采集或验收批次。

## 已实现的更新

### 上下文披露、去重与分页

- **Parent v4**：把模型看到的 Evidence 披露与程序完整 verification 解耦。程序仍读取完整授权源并核验全部结果；模型必须实际选择并成功执行 verification，计数、引用或自动重验证不能代替执行凭据。
- **Parent v5**：增加按阶段披露、就绪 brief、精确 metadata/revision 去重和更短的控制提示；完整 audit 保留在程序侧，旧 disclose 与恢复规则保持。
- **Parent v6 / v6.1 / v6.2**：增加 `context_read`、有界分页和工作集替换；绑定当前付费窗口、对象版本与页成员，在原预算内计账。v6.1 增加可严格回解的窗口 metadata 编码；v6.2 分开处理主动请求页的实际编码容量和自动预览的 legacy 增量约束。
- 增补上下文遥测、读页/恢复/撤权/篡改负控及真实分页验收脚本。v6.2 的实现和离线机制不能代替真实分页闭环证据；现有 STATUS 的该项真实补证准备状态保留。

上述版本均为显式选择，旧默认、旧付费输入及 Checkpoint 兼容不变，模型输入上限仍为 **12000 UTF-8 字节**。完整事实、证据、缺口、血缘和原完成/无进展规则保持。

### Financial / Market 领域分析

- 将既有财务、行情计算拆成可复用的领域纯算子；新增独立 Fraction 领域核验，保持原计算结果与来源语义。
- 新增版本化领域任务、结果、检查所有权、真实执行回执和可信消费接口。Child 从取证扩展到确定性计算、领域检验与局部验证。
- Parent Join 核验身份、版本、授权/PIT、快照、完整覆盖和真实持久执行凭据，不重复已验证的领域生产或局部 Fraction；Parent 仍实际执行原完整最终 verification。
- CLI 增加 `--domain-analysis-mode direct|tool|child`、`--domain-analysis-execution serial|parallel` 及独立 profile。复用原 Runtime、根预算及 Financial/Market 两域，保持显式实验入口。
- 增补同任务 A/B/C 验收脚本、安全/恢复/数据库机制测试、网络失败诊断与完整历史结果报告。

### 文档与后续设计

同步 README、ARCHITECTURE、CONSTRAINTS、PLAN、STATUS，新增上下文实施报告、领域 Child 设计/验收/最终报告及机制说明。

[业务阶段四：多因素解释研究方案](STAGE4_EXPLANATION_RESEARCH_IMPLEMENTATION_20261012.md) 新增候选解释、支持/反证、共同与区分性证据、比较结论及下一项检查的最小设计。**该部分仅有设计，业务代码、正式案例集和新实验尚未启动**；它不是研发 Phase 4 已实现功能的追加验收。

## 已有验收结论与限制

| 项目 | 实际记录 | 结论边界 |
| --- | --- | --- |
| v5 阶段披露 | 真实质量与回放均 4/4；整任务 Token 36286 → 32150，少 11.40% | 两个既有非盲案例；未证明延迟或统计优势 |
| v6 有界窗口 | 真实质量与回放均 4/4；Token 32118 → 38789，增加 20.77% | 新窗口能力成立，成本改善未成立；真实 `context_read` 为 0 |
| v6.1 精确 metadata | 真实质量与回放均 4/4；Token 38892 → 38531，少 0.9282% | 小幅限定收益；真实分页/超限恢复仍未由此证明 |
| 分析 Child | 两案例三路线最终覆盖 6/6；保留初始 4/6、窗口内复验 1/2、独立补验 1/1，共 6/9 | Child 总 Token 比领域 Tool 高 6.13%，比直接 Tool 高 137.78%；实用收益及有意义的自主检查增量未证实 |
| 历史全量工程回归 | 1159 项：1143 通过、16 数据库跳过；该 16 项另在专用隔离 PostgreSQL 通过 | 历史执行结果，本次上传不重记为新全量验收 |

旧失败、分母、未知用量及未释放预留保持，不以新成功覆盖旧未知。详细依据分别见 [v5](CONTEXT_DISCLOSURE_V5_20261007.md)、[v6](CONTEXT_WINDOW_V6_20261007.md)、[v6.1](CONTEXT_WINDOW_METADATA_V6_1_20261008.md) 和 [领域 Child 最终报告](DOMAIN_CHILD_ANALYSIS_FINAL_REPORT_20261009.md)。

## 本次上传检查

本次 **12 组离线定向检查共 165/165 通过**，覆盖领域算子、任务/结果契约、CLI、安全与恢复、metadata 编码、分页容量、v6.2 协议及旧 Parent 兼容，耗时 534.953 秒。源码编译、汇总文档链接和 `git diff --check` 均通过。未重跑全量或 PostgreSQL，不调用真实模型或金融 Provider。首次测试在系统沙箱临时目录受到 Windows 原子替换权限限制，18 项初始化报错；原日志保留，后续只将测试临时目录移至工作区，不修改生产代码或测试断言。

377 个候选项目文件的真实密钥及禁入文件扫描通过，匹配均为 0。`.env`、`test_api.txt`、`tushare.txt`、`cninfo_key.txt`、`.venv`、`.artifacts`、`.runtime` 继续排除；原始验收产物、日志和历史快照保留在本地，GitHub 上传范围为源码、测试、脚本、evaluation 与文档。

本次定向检查可从项目根目录复现；均为离线机制测试，不代表金融真值或新真实模型验收：

```powershell
$env:PYTHONPATH = 'src'
$env:PYTHONIOENCODING = 'utf-8'
$testTemp = Join-Path (Get-Location) '.runtime/github-update-tmp-20261012'
New-Item -ItemType Directory -Force $testTemp | Out-Null
$env:TEMP = $env:TMP = $testTemp
$patterns = @(
    'test_domain_operators.py', 'test_domain_analysis_contracts.py',
    'test_domain_analysis_cli.py', 'test_domain_analysis_security.py',
    'test_context_disclosure_metadata.py', 'test_context_window.py',
    'test_context_window_metadata.py', 'test_context_window_protocol.py',
    'test_context_window_security.py', 'test_context_window_requested_capacity.py',
    'test_context_window_v6_2_protocol.py', 'test_parallel_parent_progress.py'
)
foreach ($pattern in $patterns) {
    & .venv/Scripts/python.exe -m unittest discover -s tests -p $pattern -v
    if ($LASTEXITCODE -ne 0) { throw "Test group failed: $pattern" }
}
```

本地检查回执和日志：`.runtime/github-update-tests-20261012-v2.json`、`.runtime/github-update-20261012-v2-test_*.log`、`.runtime/github-upload-preflight-20261012.json`。远端提交身份与本地/远端文件树一致性另记于本轮上传回执。

暂存内容的空白检查采用 Git 的 `cr-at-eol` 选项，同时保留默认尾随空白检查；保留既有 Windows CRLF 和冻结源码字节，仅清理新设计文档的一处多余行尾空格。
