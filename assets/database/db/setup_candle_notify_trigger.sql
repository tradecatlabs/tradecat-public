-- 创建 PG NOTIFY 触发器：当 candles_1m 有数据变更时发送通知
-- 用于 K线合成器事件驱动模式

-- 1. 创建通知函数
CREATE OR REPLACE FUNCTION market_data.notify_candle_1m_update()
RETURNS TRIGGER AS $$
DECLARE
    payload JSON;
BEGIN
    -- 构建 JSON payload
    payload := json_build_object(
        'symbol', NEW.symbol,
        'bucket_ts', NEW.bucket_ts,
        'is_closed', NEW.is_closed,
        'exchange', NEW.exchange
    );
    
    -- 发送通知到 candle_1m_update 通道
    PERFORM pg_notify('candle_1m_update', payload::text);
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 2. 删除旧触发器（如果存在）
DROP TRIGGER IF EXISTS candle_1m_notify_trigger ON market_data.candles_1m;

-- 3. 创建触发器：在 INSERT 或 UPDATE 后触发
CREATE TRIGGER candle_1m_notify_trigger
AFTER INSERT OR UPDATE ON market_data.candles_1m
FOR EACH ROW
EXECUTE FUNCTION market_data.notify_candle_1m_update();

-- 4. 验证触发器是否创建成功
SELECT 
    tgname AS trigger_name,
    tgtype AS trigger_type,
    tgenabled AS enabled
FROM pg_trigger 
WHERE tgrelid = 'market_data.candles_1m'::regclass
AND tgname = 'candle_1m_notify_trigger';

-- 注意事项：
-- 1. 触发器会在每次 INSERT/UPDATE 时发送 NOTIFY
-- 2. 如果写入频率很高，可以考虑只在 is_closed=true 时触发（可选优化）
-- 3. NOTIFY 是异步的，不会阻塞写入操作
-- 4. 监听端需要使用 LISTEN candle_1m_update 来接收通知

-- 可选：只在 is_closed 变为 true 时触发（减少通知量）
-- CREATE OR REPLACE FUNCTION market_data.notify_candle_1m_closed()
-- RETURNS TRIGGER AS $$
-- BEGIN
--     IF NEW.is_closed = true AND (OLD IS NULL OR OLD.is_closed = false) THEN
--         PERFORM pg_notify('candle_1m_update', json_build_object(
--             'symbol', NEW.symbol,
--             'bucket_ts', NEW.bucket_ts,
--             'is_closed', NEW.is_closed
--         )::text);
--     END IF;
--     RETURN NEW;
-- END;
-- $$ LANGUAGE plpgsql;
