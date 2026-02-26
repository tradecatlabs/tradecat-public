-- 元数据物化视图：基于 1m 物理 K 线 + 5m 指标，统一产出多周期带指标的视图
-- 周期覆盖：1m / 5m / 15m / 1h / 4h / 1d / 1w
-- 设计要点：
--   1) 唯一数据真源仍然是 candles_1m，所有上层周期都通过连续聚合派生，避免多头写入。
--   2) 指标表 binance_futures_metrics_5m 已是 5m 粒度，这里按目标周期再聚合（last/均值），与 K 线同桶对齐。
--   3) 产出字段保持「像 1m 物理表」的 OHLCV 形态，并额外附加振幅比例 / VWAP / 多空指标等元数据。

SET search_path TO market_data, public;

CREATE OR REPLACE FUNCTION market_data._create_meta_cagg(
    p_view_name       TEXT,
    p_bucket_interval INTERVAL,
    p_start_offset    INTERVAL,
    p_end_offset      INTERVAL,
    p_schedule        INTERVAL
) RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    view_exists BOOLEAN;
    idx_name TEXT;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM timescaledb_information.continuous_aggregates
        WHERE view_schema = 'market_data' AND view_name = p_view_name
    ) INTO view_exists;

    IF NOT view_exists THEN
        EXECUTE format($fmt$
            CREATE MATERIALIZED VIEW market_data.%I
            WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
            WITH c AS (
                SELECT
                    time_bucket(%L::interval, c.bucket_ts)      AS bucket_ts,
                    c.exchange,
                    c.symbol,
                    first(c.open, c.bucket_ts)                  AS open,
                    max(c.high)                                 AS high,
                    min(c.low)                                  AS low,
                    last(c.close, c.bucket_ts)                  AS close,
                    sum(c.volume)                               AS volume,
                    sum(c.quote_volume)                         AS quote_volume,
                    sum(c.trade_count)                          AS trade_count,
                    sum(c.taker_buy_volume)                     AS taker_buy_volume,
                    sum(c.taker_buy_quote_volume)               AS taker_buy_quote_volume,
                    bool_and(c.is_closed)                       AS is_closed,
                    'meta_cagg'::text                           AS source,
                    max(c.ingested_at)                          AS ingested_at,
                    max(c.updated_at)                           AS updated_at
                FROM market_data.candles_1m c
                GROUP BY 1,2,3
            ),
            m AS (
                SELECT
                    time_bucket(%L::interval, m.create_time)    AS bucket_ts,
                    m.exchange,
                    m.symbol,
                    last(m.sum_open_interest, m.create_time)            AS open_interest,
                    last(m.sum_open_interest_value, m.create_time)      AS open_interest_value,
                    sum(m.sum_toptrader_long_short_ratio)
                        / NULLIF(sum(m.count_toptrader_long_short_ratio), 0) AS top_long_short_ratio,
                    sum(m.sum_taker_long_short_vol_ratio)
                        / NULLIF(sum(m.count_long_short_ratio), 0)      AS taker_long_short_vol_ratio,
                    max(m.create_time)                                  AS metrics_ts,
                    max(m.source)                                       AS metrics_source
                FROM market_data.binance_futures_metrics_5m m
                GROUP BY 1,2,3
            )
            SELECT
                c.bucket_ts,
                c.exchange,
                c.symbol,
                c.open, c.high, c.low, c.close,
                c.volume, c.quote_volume, c.trade_count,
                c.taker_buy_volume, c.taker_buy_quote_volume,
                c.is_closed,
                c.source,
                c.ingested_at,
                c.updated_at,
                (c.high - c.low) / NULLIF(c.close, 0)           AS amplitude_ratio,
                c.quote_volume / NULLIF(c.volume, 0)            AS vwap,
                m.open_interest,
                m.open_interest_value,
                m.top_long_short_ratio,
                m.taker_long_short_vol_ratio,
                m.metrics_ts,
                m.metrics_source
            FROM c
            LEFT JOIN m
              ON m.bucket_ts = c.bucket_ts
             AND m.exchange = c.exchange
             AND m.symbol   = c.symbol;
        $fmt$, p_view_name, p_bucket_interval, p_bucket_interval);
    END IF;

    -- 连续聚合要求唯一索引覆盖 time_bucket + 维度列
    idx_name := 'ux_' || p_view_name || '_ts_ex_symbol';
    EXECUTE format('CREATE UNIQUE INDEX IF NOT EXISTS %I ON market_data.%I (bucket_ts, exchange, symbol);',
                   idx_name, p_view_name);

    -- 刷新策略
    BEGIN
        EXECUTE format(
            'SELECT add_continuous_aggregate_policy(''market_data.%I'', start_offset => %L::interval, end_offset => %L::interval, schedule_interval => %L::interval);',
            p_view_name, p_start_offset, p_end_offset, p_schedule
        );
    EXCEPTION WHEN duplicate_object THEN
        NULL;
    END;
END;
$$;

-- 注册各周期的元数据视图
DO $$
DECLARE
    cfg RECORD;
BEGIN
    FOR cfg IN
        SELECT * FROM (VALUES
            ('candles_meta_1m',  '1 minute'::interval,  '3 days'::interval,   '1 minute'::interval,   '1 minute'::interval),
            ('candles_meta_5m',  '5 minutes',           '7 days',             '1 minute',             '1 minute'),
            ('candles_meta_15m', '15 minutes',          '14 days',            '1 minute',             '5 minutes'),
            ('candles_meta_1h',  '1 hour',              '30 days',            '5 minutes',            '5 minutes'),
            ('candles_meta_4h',  '4 hours',             '60 days',            '5 minutes',            '15 minutes'),
            ('candles_meta_1d',  '1 day',               '180 days',           '15 minutes',           '30 minutes'),
            ('candles_meta_1w',  '7 days',              '365 days',           '30 minutes',           '1 hour')
        ) AS t(view_name, bucket_interval, start_offset, end_offset, schedule_interval)
    LOOP
        PERFORM market_data._create_meta_cagg(cfg.view_name, cfg.bucket_interval, cfg.start_offset, cfg.end_offset, cfg.schedule_interval);
    END LOOP;
END$$;

