-- 连续聚合视图：由 5m 指标表上推合成 15m/1h/4h/1d/1w
-- 视图名：market_data.binance_futures_metrics_{interval}_last
-- start_offset = NULL 表示刷新全部可用数据

SET search_path TO market_data, public;

CREATE OR REPLACE FUNCTION market_data._创建指标连续聚合(
    p_view_name       TEXT,
    p_bucket_interval INTERVAL,
    p_expected_points INTEGER,
    p_origin          TIMESTAMP WITHOUT TIME ZONE,
    p_end_offset      INTERVAL,
    p_schedule        INTERVAL
) RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    view_exists BOOLEAN;
    bucket_expr TEXT;
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM timescaledb_information.continuous_aggregates
        WHERE view_schema = 'market_data' AND view_name = p_view_name
    ) INTO view_exists;

    IF NOT view_exists THEN
        IF p_origin IS NULL THEN
            bucket_expr := format('time_bucket(%L::interval, create_time)', p_bucket_interval);
        ELSE
            bucket_expr := format('time_bucket(%L::interval, create_time, %L::timestamp without time zone)', p_bucket_interval, p_origin);
        END IF;

        EXECUTE format($fmt$
            CREATE MATERIALIZED VIEW market_data.%I
            WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
            SELECT
                %s AS bucket,
                symbol,
                last(sum_open_interest, create_time) AS sum_open_interest,
                last(sum_open_interest_value, create_time) AS sum_open_interest_value,
                last(count_toptrader_long_short_ratio, create_time) AS count_toptrader_long_short_ratio,
                last(sum_toptrader_long_short_ratio, create_time) AS sum_toptrader_long_short_ratio,
                last(count_long_short_ratio, create_time) AS count_long_short_ratio,
                last(sum_taker_long_short_vol_ratio, create_time) AS sum_taker_long_short_vol_ratio,
                count(*) AS points,
                ((count(*) = %s) AND bool_and(is_closed)) AS complete
            FROM market_data.binance_futures_metrics_5m
            GROUP BY 1,2
            WITH NO DATA;
        $fmt$, p_view_name, bucket_expr, p_expected_points);
    END IF;

    -- 索引
    EXECUTE format(
        'CREATE INDEX IF NOT EXISTS %I ON market_data.%I (bucket, symbol);',
        'idx_' || p_view_name || '_bucket_symbol', p_view_name
    );

    -- start_offset => NULL 表示刷新全部历史数据
    BEGIN
        EXECUTE format(
            'SELECT add_continuous_aggregate_policy(''market_data.%I'', start_offset => NULL, end_offset => %L::interval, schedule_interval => %L::interval, if_not_exists => TRUE);',
            p_view_name, p_end_offset, p_schedule
        );
    EXCEPTION WHEN duplicate_object OR unique_violation THEN
        NULL;
    END;
END;
$$;

-- 注册各周期视图（均基于 5m 物理表）
DO $$
DECLARE
    cfg RECORD;
BEGIN
    FOR cfg IN
        SELECT * FROM (VALUES
            ('binance_futures_metrics_15m_last', '15 minutes'::interval, 3,    NULL::timestamp,                   '1 minute'::interval, '5 minutes'::interval),
            ('binance_futures_metrics_1h_last',  '1 hour'::interval,     12,   NULL::timestamp,                   '1 minute'::interval, '5 minutes'::interval),
            ('binance_futures_metrics_4h_last',  '4 hours'::interval,    48,   NULL::timestamp,                   '1 minute'::interval, '5 minutes'::interval),
            ('binance_futures_metrics_1d_last',  '1 day'::interval,      288,  NULL::timestamp,                   '1 minute'::interval, '5 minutes'::interval),
            ('binance_futures_metrics_1w_last',  '7 days'::interval,     2016, '1970-01-05 00:00:00'::timestamp, '1 minute'::interval, '5 minutes'::interval)
        ) AS t(view_name, bucket_interval, expected_points, origin, end_offset, schedule_interval)
    LOOP
        PERFORM market_data._创建指标连续聚合(cfg.view_name, cfg.bucket_interval, cfg.expected_points, cfg.origin, cfg.end_offset, cfg.schedule_interval);
    END LOOP;
END$$;
