# PLAN

1. 从 UM download collector 抽出共享模块（vision 路径、checksum、files 审计、批量入库）。
2. CM 只做：
   - rel_path 生成（futures/cm）
   - 产品维度（venue_code）区分（如果需要 core 映射）
3. 验收以“可回填 + 字段对齐 + 可审计”为准。

