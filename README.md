# V3.7 更新说明

请先阅读 [V3.7-部署与限制.md](V3.7-部署与限制.md)。本版本新增真实变更 CLI、独立超时回滚、连续多窗口智能 NAT 候选和并发探测；Web 保留只读配置草稿及事务状态。**仍非生产验收完成版**。

# MultiWAN V3.3 — 动态接口与 LAN 管理保护

> **开发预览版，不是生产可直接启用的网关。** 默认只读/保存草稿；Web 无任何修改内核网络的接口。

## 本版本新增

- 自动扫描 Linux 真实物理网卡：名称、MAC、链路状态、速率、已有 IPv4 和默认网关。**不根据网卡顺序猜测 LAN/WAN 身份**。
- 网页直接新增/移除 WAN，数量从 0 到 32 条（配置 0 条可保存草稿，但不能启用转发）；每个 WAN 可拥有 1–64 个独立 IPv4 地址及独立权重。
- 默认配置演示：`eth0=LAN`；`eth1`～`eth5` 为 WAN；`eth6`、`eth7` 未分配。网页能重新分配这些角色。系统真实网卡可能不是 `eth*`。
- LAN 必须指定网卡、CIDR 地址及直连子网；支持额外受保护管理网段，例如 `10.20.0.0/16 via 192.168.100.254`。预览时将 LAN 路由加入动态数量的策略表，运行前保护检查要求管理路由真实存在。
- 配置检验包括网口冲突、子网交叉、IP/网关合法性、管理路由下一跳与 LAN 子网关系；自动设置 Web 地址为 `127.0.0.1`。
- 网页修改只写 `config.pending.json`（权限 0600）；可通过 `/plan` 审核 Netplan、ECMP 命令、NAT 规则和配置差异。网页不包含“一键应用”操作。

## 当前仍然没有实现

- 生产级一键应用/自动超时回滚、完整权限隔离与防火墙整合；
- 将同组多公网 IP 的失败率与**实际** SNAT 地址切换联动；当前 NAT 预览仍使用每组第一个 IP；
- 已有连接跨 WAN 无损迁移、对 HTTPS 请求自动重试、目标级可靠失败率数据采集。

旧版实验性的 `--install-runtime` / `--apply` **不要在生产服务器运行**，尚未完成安全回滚与所有防火墙冲突检查。建议在网络命名空间或隔离测试机先验证。

## 快速运行（不修改本机 IP、路由和 NAT）

```bash
sudo apt install -y python3 iproute2
cd multiwan-v3
export PYTHONPATH="$PWD"
export MULTIWAN_CONFIG="$PWD/config/config.example.json"
export MULTIWAN_STATE_DIR=/tmp/multiwan-preview
export MULTIWAN_ADMIN_TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
echo "配置保存口令：$MULTIWAN_ADMIN_TOKEN"
python3 -m unittest discover -s tests -v
python3 -m multiwan.core --config "$MULTIWAN_CONFIG" --state-dir "$MULTIWAN_STATE_DIR" --once
python3 -m multiwan.web
```

本机打开 `http://127.0.0.1:8765`。Web **只监听** `127.0.0.1`，不会直接绑定 LAN/WAN。

远端查看（SSH 必须限制为信任管理来源）：

```bash
ssh -N -L 127.0.0.1:18765:127.0.0.1:8765 user@<ubuntu管理地址>
```

然后在本地浏览器访问 `http://127.0.0.1:18765`。

**操作步骤**：先选择 LAN 物理网卡/地址/网段，按需输入额外管理回程路由；然后通过“新增 WAN”“移除此 WAN”管理出口，填写网关和公网 IP 池；输入管理口令保存草稿，最后通过 `/plan` 查看变更。修改 LAN 或管理路由会被视为高风险，不会通过普通 WAN 变更流程自动应用。

如果配置演示中的接口在当前 Ubuntu 不存在，需要先在网页选择实际网卡。示例 `198.51.*` 只是占位，不代表全部都是 RFC 5737 保留网段；在真实环境部署前仍须全部按运营商地址表核实。

## 项目组成

- `multiwan/discovery.py`：物理接口发现；
- `multiwan/config_portal.py`：动态数量的配置校验、表单转换和原子草稿保存；
- `multiwan/web.py`：仅回环地址的管理 UI（Python 标准库）；
- `multiwan/deployment.py`：只读生成 Netplan / 路由 / NAT 预览；
- `multiwan/core.py`：旧版实验性 ECMP/健康检测基础逻辑；
- `tests/`：单元测试和动态数量/管理路由保护用例。

## 重要的安全界限

- 监听回环地址不意味着本机其他用户无法访问 Web；本机访问权限与 SSH 隧道访问都应使用账户认证和管理口令。不要搭建 WAN/LAN 反向代理暴露本服务。
- 完整管理路由保护需要确认操作者实际 SSH 来源网段；如果不在 LAN 直连网段，必须填写专用管理静态路由并完成真实路由检查。
- 配置草稿与预览不会更新活动网络；检查通过也不代表该组合可安全自动应用。
- 真实公网 IP、掩码、网关应由运营商参数确定。提供的示例地址必须替换。

## V3.4 蓝色卡片界面 + 故障证据日志

- 首页改为响应式蓝色卡片设计；保留原网卡自动发现、LAN 保护、动态 WAN 表单和规则预览。
- 新增 `/logs` 和 `/api/logs`：按 WAN、源公网 IP、检测目标、成功/失败与 RTT 聚合并显示日志；`window` 查询参数支持 60～86400 秒。
- 新增 `multiwan/telemetry.py`：SQLite WAL 保存探测样本与决策审计，数据库位于 `MULTIWAN_STATE_DIR/telemetry.sqlite3`。
- 实时内核 WAN 探测使用真实记录（`origin=measured`），干运行不生成假测量。只有 `timeout`、`network_error` 会进入网络失败统计，`refused`（包括应用拒绝）不算线路故障。
- 当样本不足或目标数不足时不生成故障建议；目前只是**诊断建议**，没有连接到 IP 级自动切换/接口禁用。WAN 级已有实验性 `--apply` 保持旧版功能，但不具备生产级回滚；禁止在真实现网启用。
- 现有 `probe()` 基于绑定 WAN 网口的 Ping，仅能识别接口方向可达性；不能声称测试了 20 个特定源公网 IP。要启用 IP 级自动调度，还必须新增绑定源 IP 的多目标 TCP 探针、独立对照验证与实际 SNAT 变更。
- 数据库存储是新加入的持久化事件来源，但缺少保留期/容量清理、全链路防篡改以及高并发压测；请按预览环境使用。

### 运行

```bash
export PYTHONPATH="$PWD"
export MULTIWAN_CONFIG="$PWD/config/config.example.json"
export MULTIWAN_STATE_DIR=/tmp/multiwan-preview
export MULTIWAN_ADMIN_TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
python3 -m multiwan.core --config "$MULTIWAN_CONFIG" --state-dir "$MULTIWAN_STATE_DIR" --once
python3 -m multiwan.web
```

页面：`http://127.0.0.1:8765`；日志：`http://127.0.0.1:8765/logs`。**演示环境 `/logs` 没有真实数据是正常的；不能把模拟状态当作故障证据。**

## V3.5 — 控制台视觉改版

- 全新深蓝侧边栏 + 蓝白控制台布局：仪表盘、日志分析、规则预览入口统一；支持窄屏自适应。
- 首页新增 WAN 资源卡片（显示配置数量、物理接口、公网 IP 数及权重），并保留接口自动发现与 WAN 动态增删表单。
- `/logs` 增加实际探测样本、失败数量、失败率、决策记录统计卡，以及 5 分钟、15 分钟、1 小时、24 小时窗口筛选。
- Web 继续只在 `127.0.0.1` 监听；仍属于**仅保存配置草稿和预览**的版本，不能在生产环境自动切换路由/NAT。卡片展示的是静态配置，除真实采集日志外不冒充实时 WAN 健康数据。
- **覆盖升级建议**：备份当前配置和状态目录，停止旧 Web 进程后替换程序文件，再执行 `python3 -m multiwan.web` 启动；不要覆盖已填写的正式配置文件。

## V3.6 — 源公网 IP 真实探测 + 智能 SNAT 候选池（安全预览）

- 新增 `multiwan/ip_probe.py`：依次使用各 WAN 的**指定公网源 IP**建立 IPv4 TCP 连接，对独立目标进行测量。每次探测前通过 `ip route get <目标> from <公网IP>` 核对出接口；路由不符时记为 `unknown`，**不统计为失败**。探测成功/超时/拒绝分别计入 SQLite；TCP RST/拒绝不当作线路不可达。
- 新增 `multiwan/ip_policy.py`：按每个 IP 的测量样本数、不同目标数和失败率分析；只在同组存在独立确认健康的替代公网 IP 时，建议将坏 IP 暂停参与**新连接**。不使用单窗口统计直接摘除整个 WAN。
- 新增 Web `/ip-pools` 和 `/api/ip-pools`：公网 IP 的证据统计、同组切换建议、nftables SNAT 地址池**只读预览**。
- **不会应用真实 NAT、不会改 ECMP、不会自动断开现有连接；V3.6 仍不是可生产接管现网的版本。** WAN 熔断、LAN/管理路由回滚、权限隔离、连接锁定与原子执行仍需完成并进行网络命名空间和真实八口验收。

### 本机运行真实源 IP TCP 探测（只读）

先确保真实 IP 已配置在对应接口，且 `ip route get <目标IP> from <源公网IP>` 会使用正确的 WAN；例子里的文档地址不能用于真实探测。

```bash
export PYTHONPATH="$PWD"
export MULTIWAN_STATE_DIR=/tmp/multiwan-preview
python3 -m multiwan.ip_probe --config config/config.example.json --state-dir "$MULTIWAN_STATE_DIR" --timeout 3
python3 -m multiwan.web
```

探测 20 个 IP × 2 个目标，顺序执行可能较慢；正式调度需要限速和并发上限。也可以先在测试环境通过 `python3 -m unittest discover -s tests -v` 验证，不会访问外网。访问本机 `http://127.0.0.1:8765/ip-pools` 查看建议。网页仍只监听 `127.0.0.1`。若生产环境需要更多探测目标，应使用经过批准且稳定的探测服务，避免将第三方服务当作无限制监测靶点。
