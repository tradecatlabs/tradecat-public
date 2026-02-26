-- =============================================================================
-- 滑动窗口 Retention Policy（各周期保留 500 根）
-- 执行前请备份: SELECT * FROM timescaledb_information.jobs WHERE proc_name = 'policy_retention';
-- =============================================================================

-- 移除旧策略
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN SELECT unnest(ARRAY['candles_1m','candles_5m','candles_15m','candles_1h','candles_4h','candles_1d','candles_1w'])
    LOOP
        BEGIN
            PERFORM remove_retention_policy(format('market_data.%I', tbl));
        EXCEPTION WHEN undefined_object THEN NULL;
        END;
    END LOOP;
END$$;

-- 添加新策略：500 根 × 周期间隔
DO $$
DECLARE
    cfg RECORD;
BEGIN
    FOR cfg IN
        SELECT * FROM (VALUES
            ('candles_1m',  INTERVAL '500 minutes'),   -- 8.3 小时
            ('candles_5m',  INTERVAL '2500 minutes'),  -- 41.7 小时
            ('candles_15m', INTERVAL '7500 minutes'),  -- 5.2 天
            ('candles_1h',  INTERVAL '500 hours'),     -- 20.8 天
            ('candles_4h',  INTERVAL '2000 hours'),    -- 83 天
            ('candles_1d',  INTERVAL '500 days'),      -- 1.4 年
            ('candles_1w',  INTERVAL '3500 days')      -- 9.6 年
        ) AS t(view_name, drop_after)
    LOOP
        PERFORM add_retention_policy(
            format('market_data.%I', cfg.view_name),
            drop_after => cfg.drop_after
        );
        RAISE NOTICE 'Added retention policy for % : %', cfg.view_name, cfg.drop_after;
    END LOOP;
END$$;

-- 验证
SELECT 
    hypertable_name,
    schedule_interval,
    config->>'drop_after' AS drop_after
FROM timescaledb_information.jobs 
WHERE proc_name = 'policy_retention'
  AND hypertable_schema = 'market_data'
ORDER BY hypertable_name;
