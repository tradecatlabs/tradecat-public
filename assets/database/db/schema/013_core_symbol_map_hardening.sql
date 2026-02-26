-- 013_core_symbol_map_hardening.sql
--
-- 目标：
-- - 把 symbol_map 的“语义正确性”写死在数据库层，避免半年后出现脏映射才追查。
--
-- 背景（问题）：
-- - core.symbol_map 目前只有 PRIMARY KEY (venue_id, symbol, effective_from)。
-- - 这允许同一个 (venue_id, symbol) 同时存在多条 active（effective_to IS NULL）映射；
--   上层如果用 LIMIT 1 “挑一条”，只是掩盖问题，不是阻止问题。

CREATE SCHEMA IF NOT EXISTS core;

-- 只允许每个 (venue_id, symbol) 同时存在 1 条 active 映射（effective_to IS NULL）。
CREATE UNIQUE INDEX IF NOT EXISTS uq_core_symbol_map_active
ON core.symbol_map (venue_id, symbol)
WHERE effective_to IS NULL;

-- 可选但强烈建议：只允许每个 (venue_id, instrument_id) 同时存在 1 条 active symbol。
-- 否则“按 instrument_id 反查 symbol”的 readable view 可能出现一对多，只能靠 LIMIT 1 兜底（掩盖脏数据）。
CREATE UNIQUE INDEX IF NOT EXISTS uq_core_symbol_map_active_instrument
ON core.symbol_map (venue_id, instrument_id)
WHERE effective_to IS NULL;

-- 有效期窗口必须自洽：要么永久有效（effective_to IS NULL），要么 effective_to > effective_from。
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_core_symbol_map_effective_window'
          AND conrelid = 'core.symbol_map'::regclass
    ) THEN
        EXECUTE
            'ALTER TABLE core.symbol_map ' ||
            'ADD CONSTRAINT chk_core_symbol_map_effective_window ' ||
            'CHECK (effective_to IS NULL OR effective_to > effective_from)';
    END IF;
END
$$;

-- 防止“历史窗口重叠”（真正的 as-of 语义底座）：
-- - 同一 (venue_id, symbol) 在任意时间只能映射到 1 个 instrument_id
-- - 同一 (venue_id, instrument_id) 在任意时间只能对应 1 个 symbol
-- 说明：
-- - 我们使用 [effective_from, effective_to) 半开区间；effective_to=NULL 视为 infinity
-- - 若未来要“换映射”，必须先把旧行 effective_to 关掉，再插入新行，否则会被硬约束拦住
--
-- 实现策略（跨环境更稳）：
-- - 优先使用 EXCLUDE + btree_gist（纯 DB 约束，语义最硬）
-- - 若环境不允许 CREATE EXTENSION，则降级为 trigger 检查（仍是 DB 层硬门禁，但不依赖扩展权限）

CREATE OR REPLACE FUNCTION core.trg_symbol_map_enforce_non_overlapping()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    new_range tstzrange;
BEGIN
    new_range := tstzrange(
        NEW.effective_from,
        COALESCE(NEW.effective_to, 'infinity'::timestamptz),
        '[)'
    );

    -- (venue_id, symbol) 窗口不得重叠
    IF EXISTS (
        SELECT 1
        FROM core.symbol_map s
        WHERE s.venue_id = NEW.venue_id
          AND s.symbol = NEW.symbol
          AND (TG_OP = 'INSERT' OR (s.venue_id, s.symbol, s.effective_from) <> (OLD.venue_id, OLD.symbol, OLD.effective_from))
          AND tstzrange(
                s.effective_from,
                COALESCE(s.effective_to, 'infinity'::timestamptz),
                '[)'
              ) && new_range
    ) THEN
        RAISE EXCEPTION
            'core.symbol_map 窗口重叠: (venue_id=% symbol=%) effective_from=% effective_to=%',
            NEW.venue_id,
            NEW.symbol,
            NEW.effective_from,
            NEW.effective_to;
    END IF;

    -- (venue_id, instrument_id) 窗口不得重叠
    IF EXISTS (
        SELECT 1
        FROM core.symbol_map s
        WHERE s.venue_id = NEW.venue_id
          AND s.instrument_id = NEW.instrument_id
          AND (TG_OP = 'INSERT' OR (s.venue_id, s.symbol, s.effective_from) <> (OLD.venue_id, OLD.symbol, OLD.effective_from))
          AND tstzrange(
                s.effective_from,
                COALESCE(s.effective_to, 'infinity'::timestamptz),
                '[)'
              ) && new_range
    ) THEN
        RAISE EXCEPTION
            'core.symbol_map 窗口重叠: (venue_id=% instrument_id=%) effective_from=% effective_to=%',
            NEW.venue_id,
            NEW.instrument_id,
            NEW.effective_from,
            NEW.effective_to;
    END IF;

    RETURN NEW;
END
$$;

DO $$
DECLARE
    have_btree_gist BOOLEAN;
BEGIN
    -- 若已存在 EXCLUDE 约束，则无需重复创建/降级。
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'excl_core_symbol_map_symbol_window'
          AND conrelid = 'core.symbol_map'::regclass
    ) AND EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'excl_core_symbol_map_instrument_window'
          AND conrelid = 'core.symbol_map'::regclass
    ) THEN
        RETURN;
    END IF;

    have_btree_gist := EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'btree_gist');
    IF NOT have_btree_gist THEN
        BEGIN
            EXECUTE 'CREATE EXTENSION IF NOT EXISTS btree_gist';
            have_btree_gist := TRUE;
        EXCEPTION
            WHEN insufficient_privilege OR undefined_file OR feature_not_supported THEN
                have_btree_gist := FALSE;
                RAISE NOTICE 'btree_gist 不可用（无权限或未安装），降级为 trigger 检查 core.symbol_map 窗口不重叠';
        END;
    END IF;

    IF NOT have_btree_gist THEN
        IF NOT EXISTS (
            SELECT 1
            FROM pg_trigger
            WHERE tgname = 'trg_core_symbol_map_non_overlapping'
              AND tgrelid = 'core.symbol_map'::regclass
        ) THEN
            EXECUTE $sql$
                CREATE TRIGGER trg_core_symbol_map_non_overlapping
                BEFORE INSERT OR UPDATE ON core.symbol_map
                FOR EACH ROW EXECUTE FUNCTION core.trg_symbol_map_enforce_non_overlapping()
            $sql$;
        END IF;
        RETURN;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'excl_core_symbol_map_symbol_window'
          AND conrelid = 'core.symbol_map'::regclass
    ) THEN
        EXECUTE $sql$
            ALTER TABLE core.symbol_map
            ADD CONSTRAINT excl_core_symbol_map_symbol_window
            EXCLUDE USING gist (
              venue_id WITH =,
              symbol WITH =,
              tstzrange(
                effective_from,
                COALESCE(effective_to, 'infinity'::timestamptz),
                '[)'
              ) WITH &&
            )
        $sql$;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'excl_core_symbol_map_instrument_window'
          AND conrelid = 'core.symbol_map'::regclass
    ) THEN
        EXECUTE $sql$
            ALTER TABLE core.symbol_map
            ADD CONSTRAINT excl_core_symbol_map_instrument_window
            EXCLUDE USING gist (
              venue_id WITH =,
              instrument_id WITH =,
              tstzrange(
                effective_from,
                COALESCE(effective_to, 'infinity'::timestamptz),
                '[)'
              ) WITH &&
            )
        $sql$;
    END IF;
END
$$;
