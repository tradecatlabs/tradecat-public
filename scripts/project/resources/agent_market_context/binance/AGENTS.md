# Binance Agent Market Context Resources 操作边界

本文件作用域：`scripts/project/resources/agent_market_context/binance/**`。

## 目录职责

本目录只承载 Binance skill/API 参考快照和 provenance manifest，用于后续设计 Agent-supplied market context 的契约层；它不是实时交易工具目录，也不是凭证目录。

## 强约束

- `upstream/` 与 `api-docs/` 是只读来源快照；不要在其中直接修改上游内容。
- 禁止在本目录写入 Binance API key、secret、`.env`、私钥、账户导出、真实订单日志或任何可复用凭证。
- 禁止把上游 skill 中的签名/下单/账户读取示例直接接入 TradeCat runtime。
- 当前可消费范围仅限 public/read-only market data + paper/watch；真实账户读取、签名请求和真实下单必须保持拒绝。
- 如果将来需要把某个 endpoint 提升为运行期能力，必须先新增机器契约、schema/version、错误码、provenance、测试门禁和 deterministic risk gate。

## Linear Flow

```text
Input(输入)：Agent/Hermes 需要 Binance market context 参考资料或 endpoint 分类
-> 节点1：读取 `provenance.manifest.json` 确认来源、校验和、安全边界与允许的数据族
-> 节点2：只把 `upstream/` 与 `api-docs/` 当参考快照，不执行其中签名/交易示例
-> 节点3：若需要运行期接入，先在 TradeCat 源码和 contracts 中定义 schema/version、错误码与 provenance 字段
-> 节点4：通过 tests/verify 门禁证明 public/read-only、paper/watch、no credentials、no signed requests、no real orders
-> Output(输出)：可审计的 Agent-supplied market context 契约或只读参考结论
```
