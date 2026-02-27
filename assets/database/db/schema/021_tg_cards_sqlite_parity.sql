-- TG 卡片/指标派生表（SQLite → PG 结构严格对齐）
--
-- 目的：
-- - 将原本写入 SQLite（assets/database/services/telegram-service/market_data.db）的 38 张表
--   以“同表名/同列名/同列类型映射”的方式落到 PG 中，便于最小改动切换读取端。
--
-- 约束：
-- - 表名与列名包含中文、标点、以及 `.py` 后缀；在 PG 中必须使用双引号引用。
-- - 为保持“严格对齐”，本文件不强制增加主键/唯一约束（SQLite 原表亦无）。
--   若后续需要幂等 upsert，请在写入逻辑中采用 `TRUNCATE + INSERT` 或分区删除策略。

CREATE SCHEMA IF NOT EXISTS tg_cards;

CREATE TABLE IF NOT EXISTS tg_cards."MACD柱状扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "信号概述" text,
  "MACD" double precision,
  "MACD信号线" double precision,
  "MACD柱状图" double precision,
  "DIF" double precision,
  "DEA" double precision,
  "成交额" double precision,
  "当前价格" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."KDJ随机指标扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "J值" double precision,
  "K值" double precision,
  "D值" double precision,
  "信号概述" text,
  "成交额" double precision,
  "当前价格" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."ATR波幅扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "波动分类" text,
  "ATR百分比" double precision,
  "上轨" double precision,
  "中轨" double precision,
  "下轨" double precision,
  "成交额" double precision,
  "当前价格" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."G，C点扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "EMA7" double precision,
  "EMA25" double precision,
  "EMA99" double precision,
  "价格" double precision,
  "趋势方向" text,
  "带宽评分" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."OBV能量潮扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "OBV值" double precision,
  "OBV变化率" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."CVD信号排行榜.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "CVD值" double precision,
  "变化率" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."基础数据同步器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "开盘价" double precision,
  "最高价" double precision,
  "最低价" double precision,
  "收盘价" double precision,
  "当前价格" double precision,
  "成交量" double precision,
  "成交额" double precision,
  "振幅" double precision,
  "变化率" double precision,
  "交易次数" integer,
  "成交笔数" integer,
  "主动买入量" double precision,
  "主动买量" double precision,
  "主动买额" double precision,
  "主动卖出量" double precision,
  "主动买卖比" double precision,
  "主动卖出额" double precision,
  "资金流向" double precision,
  "平均每笔成交额" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."主动买卖比扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "主动买量" double precision,
  "主动卖量" double precision,
  "主动买卖比" double precision,
  "价格" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."期货情绪元数据.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "指标" double precision,
  "持仓张数" double precision,
  "持仓金额" double precision,
  "大户多空比样本" double precision,
  "大户多空比总和" double precision,
  "全体多空比样本" double precision,
  "主动成交多空比总和" double precision,
  "大户多空比" double precision,
  "全体多空比" double precision,
  "主动成交多空比" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."K线形态扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "形态类型" text,
  "检测数量" integer,
  "强度" double precision,
  "成交额（USDT）" double precision,
  "当前价格" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."趋势线榜单.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "趋势方向" text,
  "距离趋势线%" double precision,
  "当前价格" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."全量支撑阻力扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "支撑位" double precision,
  "阻力位" double precision,
  "当前价格" double precision,
  "ATR" double precision,
  "距支撑百分比" double precision,
  "距阻力百分比" double precision,
  "距关键位百分比" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."VPVR排行生成器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "VPVR价格" double precision,
  "成交量分布" double precision,
  "价值区下沿" double precision,
  "价值区上沿" double precision,
  "价值区宽度" double precision,
  "价值区宽度百分比" double precision,
  "价值区覆盖率" double precision,
  "高成交节点" text,
  "低成交节点" text,
  "价值区位置" text,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."超级精准趋势扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "趋势方向" text,
  "趋势持续根数" double precision,
  "趋势强度" double precision,
  "趋势带" double precision,
  "最近翻转时间" text,
  "量能偏向" double precision,
  "指标" double precision,
  "信号" text
);
CREATE TABLE IF NOT EXISTS tg_cards."布林带扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "带宽" double precision,
  "中轨斜率" double precision,
  "中轨价格" double precision,
  "上轨价格" double precision,
  "下轨价格" double precision,
  "百分比b" double precision,
  "价格" double precision,
  "成交额" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."VWAP离线信号扫描.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "VWAP价格" double precision,
  "偏离度" double precision,
  "偏离百分比" double precision,
  "成交量加权" double precision,
  "当前价格" double precision,
  "成交额（USDT）" double precision,
  "VWAP上轨" double precision,
  "VWAP下轨" double precision,
  "VWAP带宽" double precision,
  "VWAP带宽百分比" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."成交量比率扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "量比" double precision,
  "信号概述" text,
  "成交额" double precision,
  "当前价格" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."MFI资金流量扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "MFI值" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."流动性扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "流动性得分" double precision,
  "流动性等级" text,
  "Amihud得分" double precision,
  "Kyle得分" double precision,
  "波动率得分" double precision,
  "成交量得分" double precision,
  "Amihud原值" double precision,
  "Kyle原值" double precision,
  "成交额（USDT）" double precision,
  "当前价格" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."智能RSI扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "信号" text,
  "方向" text,
  "强度" double precision,
  "RSI均值" double precision,
  "RSI7" double precision,
  "RSI14" double precision,
  "RSI21" double precision,
  "位置" text,
  "背离" text,
  "超买阈值" double precision,
  "超卖阈值" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."趋势云反转扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "信号" text,
  "方向" text,
  "强度" double precision,
  "形态" text,
  "SMMA200" double precision,
  "EMA2" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."大资金操盘扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "信号" text,
  "方向" text,
  "评分" double precision,
  "结构事件" text,
  "偏向" text,
  "订单块" text,
  "订单块上沿" double precision,
  "订单块下沿" double precision,
  "缺口类型" text,
  "价格区域" text,
  "摆动高点" double precision,
  "摆动低点" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."量能斐波狙击扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "信号" text,
  "方向" text,
  "强度" double precision,
  "价格区域" text,
  "VWMA基准" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."零延迟趋势扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "信号" text,
  "方向" text,
  "强度" double precision,
  "ZLEMA" double precision,
  "波动带宽" double precision,
  "上轨" double precision,
  "下轨" double precision,
  "趋势值" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."量能信号扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "信号" text,
  "方向" text,
  "强度" double precision,
  "多头比例" double precision,
  "空头比例" double precision,
  "MA100" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."多空信号扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "信号" text,
  "方向" text,
  "强度" double precision,
  "颜色" text,
  "实体大小" double precision,
  "影线长度" double precision,
  "HA开盘" double precision,
  "HA收盘" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."剥头皮信号扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "剥头皮信号" text,
  "RSI" double precision,
  "EMA9" double precision,
  "EMA21" double precision,
  "当前价格" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."谐波信号扫描器.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "谐波值" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."期货情绪聚合表.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "信号" text,
  "是否闭合" double precision,
  "数据新鲜秒" double precision,
  "持仓金额" double precision,
  "持仓张数" double precision,
  "大户多空比" double precision,
  "全体多空比" double precision,
  "主动成交多空比" double precision,
  "大户样本" double precision,
  "持仓变动" double precision,
  "持仓变动%" double precision,
  "大户偏离" double precision,
  "全体偏离" double precision,
  "主动偏离" double precision,
  "情绪差值" double precision,
  "情绪差值绝对值" double precision,
  "波动率" double precision,
  "OI连续根数" double precision,
  "主动连续根数" double precision,
  "风险分" double precision,
  "市场占比" double precision,
  "大户波动" double precision,
  "全体波动" double precision,
  "持仓斜率" double precision,
  "持仓Z分数" double precision,
  "大户情绪动量" double precision,
  "主动情绪动量" double precision,
  "情绪翻转信号" double precision,
  "主动跳变幅度" double precision,
  "稳定度分位" double precision,
  "贡献度排名" double precision,
  "陈旧标记" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."SuperTrend.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "SuperTrend" double precision,
  "方向" text,
  "上轨" double precision,
  "下轨" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."ADX.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "ADX" double precision,
  "正向DI" double precision,
  "负向DI" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."CCI.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "CCI" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."WilliamsR.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "WilliamsR" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."Donchian.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "上轨" double precision,
  "中轨" double precision,
  "下轨" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."Keltner.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "上轨" double precision,
  "中轨" double precision,
  "下轨" double precision,
  "ATR" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."Ichimoku.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "转换线" double precision,
  "基准线" double precision,
  "先行带A" double precision,
  "先行带B" double precision,
  "迟行带" double precision,
  "当前价格" double precision,
  "信号" text,
  "方向" text,
  "强度" double precision,
  "指标" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."数据监控.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "已加载根数" integer,
  "最新时间" text,
  "本周应有根数" double precision,
  "缺口" double precision
);
CREATE TABLE IF NOT EXISTS tg_cards."期货情绪缺口监控.py" (
"交易对" text,
  "周期" text,
  "数据时间" text,
  "信号" text,
  "已加载根数" double precision,
  "最新时间" text,
  "缺失根数" double precision,
  "首缺口起" text,
  "首缺口止" text
);

