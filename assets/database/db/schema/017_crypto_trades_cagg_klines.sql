-- 017_crypto_trades_cagg_klines.sql
--
-- 目标：
-- - 基于 trades 事实表构建“可重复计算、可持续刷新”的 K 线派生序列（Timescale continuous aggregates）。
-- - 单一真相源：K 线只来自 trades（不允许多头写入）。
--
-- 重要约定：
-- - futures UM/CM：time=epoch(ms)，bucket_width=60000(ms)
-- - spot：time=epoch(us)，bucket_width=60000000(us)
-- - open/close 的排序键使用 trade id（Binance trades id 单调递增），避免同一 time(ms/us) 内多笔成交导致 first/last 不稳定。
--
-- 依赖：
-- - 009_crypto_binance_vision_landing.sql（raw trades）
--
-- 说明：
-- - 本脚本只创建 cagg（WITH NO DATA），不会立刻全量回算历史（避免一次性爆炸）。
--   首次初始化请按任务文档对指定日期范围手动 refresh。

CREATE SCHEMA IF NOT EXISTS crypto;

-- ==================== futures UM 1m klines ====================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM timescaledb_information.continuous_aggregates
        WHERE view_schema = 'crypto'
          AND view_name = 'cagg_futures_um_klines_1m'
    ) THEN
        EXECUTE $sql$
        CREATE MATERIALIZED VIEW crypto.cagg_futures_um_klines_1m
        WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
        SELECT
            time_bucket(60000, time) AS bucket_ms,
            venue_id,
            instrument_id,
            first(price, id) AS open,
            max(price) AS high,
            min(price) AS low,
            last(price, id) AS close,
            sum(qty) AS volume,
            sum(quote_qty) AS quote_volume,
            count(*) AS trade_count,
            sum(qty) FILTER (WHERE is_buyer_maker = false) AS taker_buy_volume,
            sum(quote_qty) FILTER (WHERE is_buyer_maker = false) AS taker_buy_quote_volume,
            min(id) AS first_id,
            max(id) AS last_id
        FROM crypto.raw_futures_um_trades
        GROUP BY 1,2,3
        WITH NO DATA
        $sql$;
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_cagg_futures_um_klines_1m_bucket_vid_iid
ON crypto.cagg_futures_um_klines_1m (bucket_ms, venue_id, instrument_id);

DO $$
BEGIN
    PERFORM add_continuous_aggregate_policy(
        'crypto.cagg_futures_um_klines_1m',
        -- 连续聚合基于整数时间轴（ms），policy 的 start/end offset 也必须使用 bigint(ms)
        start_offset => 2592000000::BIGINT, -- 30 days * 86400000(ms)
        end_offset => 300000::BIGINT,       -- 5 minutes * 60000(ms)
        schedule_interval => INTERVAL '1 minute'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_parameter_value THEN
        -- 二次执行会报：continuous aggregate refresh policy already exists ...
        IF POSITION('refresh policy already exists' IN SQLERRM) > 0 THEN
            NULL;
        ELSE
            RAISE;
        END IF;
END$$;

-- ==================== futures CM 1m klines ====================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM timescaledb_information.continuous_aggregates
        WHERE view_schema = 'crypto'
          AND view_name = 'cagg_futures_cm_klines_1m'
    ) THEN
        EXECUTE $sql$
        CREATE MATERIALIZED VIEW crypto.cagg_futures_cm_klines_1m
        WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
        SELECT
            time_bucket(60000, time) AS bucket_ms,
            venue_id,
            instrument_id,
            first(price, id) AS open,
            max(price) AS high,
            min(price) AS low,
            last(price, id) AS close,
            sum(qty) AS volume,
            sum(quote_qty) AS quote_volume,
            count(*) AS trade_count,
            sum(qty) FILTER (WHERE is_buyer_maker = false) AS taker_buy_volume,
            sum(quote_qty) FILTER (WHERE is_buyer_maker = false) AS taker_buy_quote_volume,
            min(id) AS first_id,
            max(id) AS last_id
        FROM crypto.raw_futures_cm_trades
        GROUP BY 1,2,3
        WITH NO DATA
        $sql$;
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_cagg_futures_cm_klines_1m_bucket_vid_iid
ON crypto.cagg_futures_cm_klines_1m (bucket_ms, venue_id, instrument_id);

DO $$
BEGIN
    PERFORM add_continuous_aggregate_policy(
        'crypto.cagg_futures_cm_klines_1m',
        start_offset => 2592000000::BIGINT, -- ms
        end_offset => 300000::BIGINT,       -- ms
        schedule_interval => INTERVAL '1 minute'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_parameter_value THEN
        IF POSITION('refresh policy already exists' IN SQLERRM) > 0 THEN
            NULL;
        ELSE
            RAISE;
        END IF;
END$$;

-- ==================== spot 1m klines ====================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM timescaledb_information.continuous_aggregates
        WHERE view_schema = 'crypto'
          AND view_name = 'cagg_spot_klines_1m'
    ) THEN
        EXECUTE $sql$
        CREATE MATERIALIZED VIEW crypto.cagg_spot_klines_1m
        WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
        SELECT
            time_bucket(60000000, time) AS bucket_us,
            venue_id,
            instrument_id,
            first(price, id) AS open,
            max(price) AS high,
            min(price) AS low,
            last(price, id) AS close,
            sum(qty) AS volume,
            sum(quote_qty) AS quote_volume,
            count(*) AS trade_count,
            sum(qty) FILTER (WHERE is_buyer_maker = false) AS taker_buy_volume,
            sum(quote_qty) FILTER (WHERE is_buyer_maker = false) AS taker_buy_quote_volume,
            min(id) AS first_id,
            max(id) AS last_id
        FROM crypto.raw_spot_trades
        GROUP BY 1,2,3
        WITH NO DATA
        $sql$;
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_cagg_spot_klines_1m_bucket_vid_iid
ON crypto.cagg_spot_klines_1m (bucket_us, venue_id, instrument_id);

DO $$
BEGIN
    PERFORM add_continuous_aggregate_policy(
        'crypto.cagg_spot_klines_1m',
        -- spot 的整数时间轴单位为 us
        start_offset => 2592000000000::BIGINT, -- 30 days in us
        end_offset => 300000000::BIGINT,       -- 5 minutes in us
        schedule_interval => INTERVAL '1 minute'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN invalid_parameter_value THEN
        IF POSITION('refresh policy already exists' IN SQLERRM) > 0 THEN
            NULL;
        ELSE
            RAISE;
        END IF;
END$$;
