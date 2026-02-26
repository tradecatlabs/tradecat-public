-- 连续聚合视图：由 1m 基础数据实时合成多周期 K 线
-- 仅保留核心周期：5m, 15m, 1h, 4h, 1d, 1w
-- start_offset = NULL 表示刷新全部可用数据

SET search_path TO market_data, public;

CREATE OR REPLACE FUNCTION market_data._创建连续聚合(
    p_view_name       TEXT,
    p_bucket_interval INTERVAL,
    p_end_offset      INTERVAL,
    p_schedule        INTERVAL
) RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    view_exists BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM timescaledb_information.continuous_aggregates
        WHERE view_schema = 'market_data' AND view_name = p_view_name
    ) INTO view_exists;

    IF NOT view_exists THEN
        EXECUTE format($fmt$
            CREATE MATERIALIZED VIEW market_data.%I
            WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
            SELECT
                exchange,
                symbol,
                time_bucket(%L::interval, bucket_ts)           AS bucket_ts,
                first(open, bucket_ts)                         AS open,
                max(high)                                      AS high,
                min(low)                                       AS low,
                last(close, bucket_ts)                         AS close,
                sum(volume)                                    AS volume,
                sum(quote_volume)                              AS quote_volume,
                sum(trade_count)                               AS trade_count,
                bool_and(is_closed)                            AS is_closed,
                'cagg'                                         AS source,
                max(ingested_at)                               AS ingested_at,
                max(updated_at)                                AS updated_at,
                sum(taker_buy_volume)                          AS taker_buy_volume,
                sum(taker_buy_quote_volume)                    AS taker_buy_quote_volume
            FROM market_data.candles_1m
            GROUP BY exchange, symbol, time_bucket(%L::interval, bucket_ts);
        $fmt$, p_view_name, p_bucket_interval, p_bucket_interval);
    END IF;

    -- start_offset => NULL 表示刷新全部历史数据
    BEGIN
        EXECUTE format(
            'SELECT add_continuous_aggregate_policy(''market_data.%I'', start_offset => NULL, end_offset => %L::interval, schedule_interval => %L::interval, if_not_exists => TRUE);',
            p_view_name, p_end_offset, p_schedule
        );
    -- timescaledb 版本差异下，重复策略可能抛 duplicate_object 或 unique_violation；
    -- 这里按幂等语义吞掉“已存在”的情况。
    EXCEPTION WHEN duplicate_object OR unique_violation THEN
        NULL;
    END;
END;
$$;

DO $$
DECLARE
    cfg RECORD;
BEGIN
    FOR cfg IN
        SELECT * FROM (VALUES
            -- 核心周期：start_offset = NULL（刷新全部），end_offset = 1分钟，schedule = 1分钟
            ('candles_5m',  '5 minutes'::interval,  '1 minute'::interval, '1 minute'::interval),
            ('candles_15m', '15 minutes',           '1 minute',           '1 minute'),
            ('candles_1h',  '1 hour',               '1 minute',           '1 minute'),
            ('candles_4h',  '4 hours',              '1 minute',           '1 minute'),
            ('candles_1d',  '1 day',                '1 minute',           '1 minute'),
            ('candles_1w',  '7 days',               '1 minute',           '1 minute')
        ) AS t(view_name, bucket_interval, end_offset, schedule_interval)
    LOOP
        PERFORM market_data._创建连续聚合(cfg.view_name, cfg.bucket_interval, cfg.end_offset, cfg.schedule_interval);
    END LOOP;
END$$;
