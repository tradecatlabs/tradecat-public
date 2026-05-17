from __future__ import annotations

import unittest

from tradecat_auto.tradecat_source import (
    event_id_for,
    parse_anomaly_symbols,
    parse_event_stream_payload,
)


class TradeCatSourceTests(unittest.TestCase):
    def test_event_id_uses_timestamp_and_content_not_timestamp_only(self) -> None:
        first = event_id_for("2026-05-13 12:00:00", "BTCUSDT one")
        second = event_id_for("2026-05-13 12:00:00", "ETHUSDT two")

        self.assertNotEqual(first, second)
        self.assertEqual(first, event_id_for("2026-05-13 12:00:00", "BTCUSDT one"))

    def test_parses_event_stream_payload_into_stable_sheet_events(self) -> None:
        payload = {
            "schema": "tradecat.request_result.v1",
            "ok": True,
            "dataset_key": "event_stream",
            "rows": [
                {"时间(北京)": "2026-05-13 12:00:00", "内容": "BTCUSDT 出现大幅波动"},
                {"时间(北京)": "", "内容": "missing time skipped"},
                {"时间(北京)": "2026-05-13 12:01:00", "内容": ""},
            ],
        }

        result = parse_event_stream_payload(payload)

        self.assertEqual(result["schema"], "tradecat_auto.sheet_events.v1")
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["events"][0]["source_time_bj"], "2026-05-13 12:00:00")
        self.assertEqual(result["events"][0]["content"], "BTCUSDT 出现大幅波动")
        self.assertIn("event_id", result["events"][0])

    def test_parses_anomaly_symbols_and_normalizes_against_tradable_universe(self) -> None:
        payload = {
            "ok": True,
            "dataset_key": "anomaly_panel",
            "rows": [
                {"序号": "1", "交易对": "IRYS", "5m量变化率": "-1.84%"},
                {"序号": "2", "交易对": "BTCUSDT", "5m量变化率": "1.20%"},
                {"序号": "3", "交易对": "NOPE", "5m量变化率": "9.99%"},
                {"序号": "4", "交易对": "IRYS", "5m量变化率": "2.00%"},
            ],
        }

        result = parse_anomaly_symbols(payload, tradable_symbols={"IRYSUSDT", "BTCUSDT"})

        self.assertEqual(result["schema"], "tradecat_auto.anomaly_symbols.v1")
        self.assertEqual([item["normalized_symbol"] for item in result["symbols"]], ["IRYSUSDT", "BTCUSDT"])
        self.assertEqual(result["rejected"][0]["raw_symbol"], "NOPE")
        self.assertEqual(result["rejected"][0]["reason"], "not_in_tradable_usdt_perp_universe")


if __name__ == "__main__":
    unittest.main()
