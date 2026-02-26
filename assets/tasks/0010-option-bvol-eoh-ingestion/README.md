# 0010 - option-bvol-eoh-ingestion

## 价值（Why）

期权侧的 `BVOLIndex/EOHSummary` 属于官方提供且难以从现货/期货原子数据还原的序列/汇总数据。  
本任务把期权数据从“占位”补齐到可回填、可审计、可查询的形态，为后续波动率/期权因子研究打底。

## 范围（Scope）

### In Scope

- 下载回填：
  - `crypto.data_download.option.BVOLIndex`
  - `crypto.data_download.option.EOHSummary`
- 入库目标：
  - `crypto.raw_option_bvol_index`
  - `crypto.raw_option_eoh_summary`
- 对齐官方字段解析（空字符串→NULL 等）。

### Out of Scope

- 不做期权实时流（ccxtpro 期权覆盖不稳定，且官方数据为日度汇总为主）。

