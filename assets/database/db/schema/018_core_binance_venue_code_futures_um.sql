-- 018_core_binance_venue_code_futures_um.sql
--
-- 目标：
-- - 统一 Binance 的“产品维度键空间”命名：binance_futures_um / binance_futures_cm / binance_spot / ...
--
-- 背景：
-- - 早期运行库可能把 futures_um 落在 venue_code=binance 下；
-- - 采集代码现已要求 futures_um 使用 venue_code=binance_futures_um（避免与 spot/cm/option 同名 symbol 撞车）。
--
-- 策略：
-- - 不改 venue_id（事实表只存 venue_id），只改 venue_code（维表可读性字段）。
-- - 若同时存在 binance 与 binance_futures_um，两条 venue 需要手工合并（脚本 fail-fast）。

DO $$
DECLARE
    old_id BIGINT;
    new_id BIGINT;
BEGIN
    IF to_regclass('core.venue') IS NULL THEN
        RAISE NOTICE 'skip: core.venue 不存在';
        RETURN;
    END IF;

    SELECT venue_id INTO old_id FROM core.venue WHERE venue_code = 'binance' LIMIT 1;
    SELECT venue_id INTO new_id FROM core.venue WHERE venue_code = 'binance_futures_um' LIMIT 1;

    IF old_id IS NULL AND new_id IS NULL THEN
        RAISE NOTICE 'skip: core.venue 中不存在 binance/binance_futures_um';
        RETURN;
    END IF;

    IF old_id IS NOT NULL AND new_id IS NOT NULL THEN
        RAISE EXCEPTION
            'abort: core.venue 同时存在 binance(venue_id=%) 与 binance_futures_um(venue_id=%)，需要手工合并/清理后再执行',
            old_id,
            new_id;
    END IF;

    IF new_id IS NOT NULL THEN
        RAISE NOTICE 'ok: binance_futures_um 已存在 (venue_id=%)，无需迁移', new_id;
        RETURN;
    END IF;

    UPDATE core.venue
    SET venue_code = 'binance_futures_um',
        venue_name = COALESCE(NULLIF(venue_name, ''), 'binance_futures_um')
    WHERE venue_id = old_id;

    RAISE NOTICE 'ok: core.venue venue_id=% 已从 binance 改名为 binance_futures_um', old_id;
END
$$;

