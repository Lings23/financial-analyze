# 第二轮实验连接故障原因分析（2026-10-09）

结论：已在不带密钥、不带金融数据、不调用模型的独立诊断中复现 **TCP connect 阶段的间歇性超时**。这明显支持客户端到受控API入口之间建连路径不稳定的判断。尚不能定位是本机过滤、内网网关、运营商路径或远端入口策略，也不能追认历史未知付费请求没有到达服务端。

## 直接证据

2026-10-09 16:05:15–16:05:40（+08:00），对受控端点当前解析的两个IPv4地址各做三个固定样本，远端端口443，分别计时TCP、TLS和无Authorization的HTTP HEAD。没有金融Provider请求、模型POST或历史未知请求重发。

| 目的IP | 第一次TCP | 第二次TCP | 第三次TCP |
| --- | --- | --- | --- |
| 47.94.20.201 | 1016ms成功 | 3031ms成功 | 21031ms失败，Windows 10060 |
| 101.201.58.201 | 1047ms成功 | 3031ms成功 | 7063ms成功 |

失败明确发生在`socket.connect()`，TLS尚未开始。成功的五次连接随后都通过默认CA和主机名校验，TLSv1.3耗时15–46ms；HTTP HEAD在0–16ms返回401。该401是无凭据探测的预期鉴权拒绝，仅证明HTTP入口可响应，不是实际模型密钥错误，也不是业务模型验收成功。

原15:50:13–15:50:34付费失败耗时21048ms，与本次TCP超时21031ms非常接近。因此原失败也发生于TCP建连是有根据的推断；由于旧付费回执没有分阶段信息，不能把推断写成历史事实或据此释放8544 Token未知预留。此前将泛化直连超时称作“TLS握手超时”证据不足，本次应明确为TCP层已复现。

## 对可能原因的判断

- **TCP握手路径上的丢包、丢弃或入口连接限制：最符合当前证据。** 成功连接也出现约1、3、7秒的台阶式延迟，与等待和重传相容。没有抓包，尚不能确定SYN是否离开本机或SYN-ACK在哪里丢失，也不能认定某个设备为责任方。
- **本地显式HTTP代理不是必要条件。** 新样本直接建立AF_INET socket。16:04只读路由显示两个目标都通过物理以太网和现有网关，未发现TUN网卡承载这两个路由的证据。Clash相关进程正在运行，不足以证明流量经过它；路由检查也不能排除其他WFP过滤。
- **代理路径还有独立的间歇性问题。** 历史六个CONNECT/TLS样本中有一次5016ms的SSLEOFError，说明代理或其上游可能提前关闭TLS连接。但这个现象不能解释全部无代理TCP失败。
- **IPv6等待是早先诊断中的附加问题。** 历史两个IPv6地址都在TCP阶段超时；最新付费续验及本次诊断已显式IPv4，因此IPv6不是最新这次失败的解释。
- **持续性的证书、模型标识、请求语法或财务输入错误，缺乏支持。** 本次故障在TLS/HTTP之前即可复现；成功样本的TLS校验与HTTP入口正常。实际模型端点曾返回同模型成功响应，但这只证明当次可用，不能保证下一次TCP连接成功。

本机当前`netsh interface tcp show global`显示Initial RTO=1000ms、Max SYN Retransmissions=4。不能机械套用其他Windows版本“3+6+12=21秒”的默认说明来推导本机具体重传序列；本次21秒结论来自实际connect失败计时与10060错误码。

## 为什么此前定位不清

原`ChatHTTPTransport`将URLError、TimeoutError、socket.timeout和OSError统一转成`ModelConnectionError`，且不保留底层`reason`、`errno/winerror`、目标IP和阶段；新IPv4实例复用该错误映射。这保护了回执不泄露头部或凭据，但也让DNS/TCP/TLS/HTTP收发故障难以区分。此处是可观测性缺口，不能直接归为业务算子或模型故障。

后续最有价值的动作是对两个目的IP的443端口做限定TCP握手抓包，结合本机及网关日志确认SYN/SYN-ACK方向；同时为未来显式传输版本记录安全的stage、目标IP、阶段耗时、errno/winerror及是否已经发送HTTP字节。不记录密钥、Authorization或请求正文。已有冻结代码、付费wire和未知预算不改，本次没有修改网络配置或发起新的付费验收。

## 证据与来源

- [分阶段实测](../.runtime/domain-analysis-network-stage-diagnosis-20261009.json)，6次TCP尝试、5次TLS、5次无凭据HEAD、0模型请求。
- [可复核诊断脚本](../.runtime/domain-analysis-network-stage-diagnosis-20261009.py)，固定样本，TCP23秒、TLS6秒、HEAD6秒上限；证据已存在时拒绝覆盖。
- [网卡、路由与TCP设置](../.runtime/domain-analysis-network-settings-diagnosis-20261009.json)。
- [原付费失败区间](../.artifacts/domain-analysis/verification-continuation-20261009/live/dispatch/004-interval.json)及[原回执](../.artifacts/domain-analysis/verification-continuation-20261009/live/dispatch/004-receipt.json)，仅能证明结果未知。
- [Microsoft：connect错误语义](https://learn.microsoft.com/en-us/windows/win32/api/winsock2/nf-winsock2-connect)，WSAETIMEDOUT属于建连失败；[TCP/IP连通性排查](https://learn.microsoft.com/en-us/troubleshoot/windows-client/networking/tcp-ip-connectivity-issues-troubleshooting)说明需结合握手重传与过滤位置定位。
- [Python：URLError.reason](https://docs.python.org/3.14/library/urllib.error.html)，底层reason可提供进一步错误信息；本次旧适配器没有将其安全分类保留到回执。

本分析不改变工程/业务验收评分。第二轮真实业务闭环仍未完成，旧未知请求和全部22338 Token未知预留仍保留。
