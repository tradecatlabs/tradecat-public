from __future__ import annotations

import unittest
from unittest.mock import patch

from tradecat_auto.tradecat_source import (
    TradeCatPublicSource,
    anomaly_signal_events_payload,
    event_id_for,
    parse_anomaly_symbols,
    parse_event_stream_payload,
    parse_signal_flow_payload,
    signal_events_payload,
    signal_flow_event_id_for,
)


class TradeCatSourceTests(unittest.TestCase):
    def test_event_id_uses_timestamp_and_content_not_timestamp_only(self) -> None:
        first = event_id_for("2026-05-13 12:00:00", "BTCUSDT one")
        second = event_id_for("2026-05-13 12:00:00", "ETHUSDT two")

        self.assertNotEqual(first, second)
        self.assertEqual(first, event_id_for("2026-05-13 12:00:00", "BTCUSDT one"))

    def test_signal_flow_event_id_uses_semantic_key_not_physical_row(self) -> None:
        row = {
            "时间(北京)": "2026-05-18 17:40:48",
            "交易对": "FORM",
            "周期": "5分钟",
            "类型": "成交额暴增",
            "内容": "成交额暴增；方向=提醒，强度=70，价格=4.8405",
        }

        first = signal_flow_event_id_for(row, row_index=1, normalized_symbol="FORMUSDT")
        second = signal_flow_event_id_for({**row, "交易对": "FORMUSDT", "源行号": 99}, row_index=99, normalized_symbol="FORMUSDT")

        self.assertEqual(first, second)

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

    def test_event_stream_preserves_remote_source_error(self) -> None:
        result = parse_event_stream_payload(
            {
                "schema": "tradecat.request_result.v1",
                "ok": False,
                "dataset_key": "event_stream",
                "error": {"code": "remote_http_status", "status": 404},
            }
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "remote_http_status")
        self.assertEqual(result["error"]["status"], 404)
        self.assertEqual(result["events"], [])

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

    def test_parses_anomaly_symbols_from_all_sectioned_boards(self) -> None:
        payload = {
            "ok": True,
            "dataset_key": "anomaly_panel",
            "rows": [
                {"榜单": "5m 异动榜", "源行号": "8", "序号": "1", "交易对": "FF", "5m量变化率": "-0.082%"},
                {
                    "榜单": "15m 异动榜",
                    "源行号": "16",
                    "序号": "1",
                    "交易对": "MORPHO",
                    "15m量变化率": "2.939%",
                },
                {
                    "榜单": "1h 异动榜",
                    "源行号": "24",
                    "序号": "1",
                    "交易对": "FIDA",
                    "1h量变化率": "7.918%",
                },
            ],
        }

        result = parse_anomaly_symbols(payload, tradable_symbols={"FFUSDT", "MORPHOUSDT", "FIDAUSDT"})

        self.assertEqual(result["ok"], True)
        self.assertEqual([item["normalized_symbol"] for item in result["symbols"]], ["FFUSDT", "MORPHOUSDT", "FIDAUSDT"])
        self.assertEqual([item["section"] for item in result["rows"]], ["5m 异动榜", "15m 异动榜", "1h 异动榜"])
        self.assertEqual(result["rows"][1]["first_row_index"], 16)
        self.assertEqual(result["rows"][2]["source_values"]["1h量变化率"], "7.918%")
        self.assertEqual(
            result["sections"],
            [
                {"name": "5m 异动榜", "row_count": 1},
                {"name": "15m 异动榜", "row_count": 1},
                {"name": "1h 异动榜", "row_count": 1},
            ],
        )

    def test_builds_stable_anomaly_signal_event_from_anomaly_panel_row(self) -> None:
        anomaly = {
            "schema": "tradecat_auto.anomaly_symbols.v1",
            "ok": True,
            "source_dataset_key": "anomaly_panel",
            "symbols": [
                {
                    "raw_symbol": "IRYS",
                    "normalized_symbol": "IRYSUSDT",
                    "first_row_index": 2,
                    "source_dataset_key": "anomaly_panel",
                    "source_values": {
                        "交易对": "IRYS",
                        "时间(北京)": "2026-05-18 17:08:43",
                        "5m量变化率": "-1.84%",
                    },
                }
            ],
            "rejected": [],
        }

        first = anomaly_signal_events_payload(anomaly, selected_symbol="IRYSUSDT")
        second = anomaly_signal_events_payload(anomaly, selected_symbol="IRYSUSDT")

        self.assertEqual(first["schema"], "tradecat_auto.anomaly_signal_events.v1")
        self.assertTrue(first["ok"])
        self.assertEqual(first["source_dataset_key"], "anomaly_panel")
        self.assertEqual(first["events"][0]["source_dataset_key"], "anomaly_panel")
        self.assertEqual(first["events"][0]["symbol"], "IRYSUSDT")
        self.assertEqual(first["events"][0]["source_time_bj"], "2026-05-18 17:08:43")
        self.assertIn("IRYSUSDT 异动面板信号", first["events"][0]["content"])
        self.assertEqual(first["events"][0]["event_id"], second["events"][0]["event_id"])

    def test_signal_flow_events_preserve_full_row_and_related_anomaly(self) -> None:
        signal_flow = parse_signal_flow_payload(
            {
                "schema": "tradecat.request_result.v1",
                "ok": True,
                "dataset_key": "signal_flow",
                "rows": [
                    {
                        "时间(北京)": "2026-05-18 17:40:48",
                        "交易对": "FORM",
                        "周期": "5分钟",
                        "类型": "成交额暴增",
                        "内容": "成交额暴增；方向=提醒，强度=70，价格=4.8405",
                    }
                ],
            },
            tradable_symbols={"FORMUSDT"},
        )
        anomaly = parse_anomaly_symbols(
            {
                "schema": "tradecat.request_result.v1",
                "ok": True,
                "dataset_key": "anomaly_panel",
                "rows": [
                    {
                        "交易对": "FORM",
                        "5m量变化率": "0.909%",
                        "5m额变化率": "-3.657%",
                        "量额背离": "-4.565%",
                        "现持仓额": "5667814.63",
                    }
                ],
            },
            tradable_symbols={"FORMUSDT"},
        )

        events = signal_events_payload(signal_flow, anomaly, selected_symbol="FORMUSDT")

        self.assertEqual(events["schema"], "tradecat_auto.signal_events.v1")
        self.assertTrue(events["ok"])
        self.assertEqual(events["source_dataset_key"], "signal_flow")
        event = events["events"][0]
        self.assertEqual(event["symbol"], "FORMUSDT")
        self.assertEqual(event["period"], "5分钟")
        self.assertEqual(event["signal_type"], "成交额暴增")
        self.assertIn("周期=5分钟", event["content"])
        self.assertIn("5m额变化率=-3.657%", event["content"])
        self.assertEqual(event["source_values"]["内容"], "成交额暴增；方向=提醒，强度=70，价格=4.8405")
        self.assertEqual(event["related_anomaly_panel"]["source_values"]["现持仓额"], "5667814.63")

    def test_signal_flow_payload_deduplicates_incremental_event_push_rows(self) -> None:
        duplicate = {
            "时间(北京)": "2026-05-18 17:40:48",
            "交易对": "FORM",
            "周期": "5分钟",
            "类型": "成交额暴增",
            "内容": "成交额暴增；方向=提醒，强度=70，价格=4.8405",
        }
        result = parse_signal_flow_payload(
            {
                "schema": "tradecat.request_result.v1",
                "ok": True,
                "dataset_key": "signal_flow",
                "rows": [
                    duplicate,
                    {**duplicate, "源行号": 22},
                    {**duplicate, "时间(北京)": "2026-05-18 17:41:48"},
                ],
            },
            tradable_symbols={"FORMUSDT"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["events"]), 2)
        self.assertEqual(result["duplicate_count"], 1)
        self.assertEqual(result["duplicates"][0]["reason"], "duplicate_signal_flow_event")
        self.assertEqual(result["duplicates"][0]["first_row_index"], 1)
        self.assertEqual(result["events"][0]["row_index"], 1)
        self.assertEqual(result["events"][1]["row_index"], 3)

    def test_anomaly_symbols_preserves_remote_source_error(self) -> None:
        result = parse_anomaly_symbols(
            {
                "schema": "tradecat.request_result.v1",
                "ok": False,
                "dataset_key": "anomaly_panel",
                "error": {"code": "remote_http_status", "status": 404},
            },
            tradable_symbols={"IRYSUSDT"},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "remote_http_status")
        self.assertEqual(result["error"]["status"], 404)
        self.assertEqual(result["symbols"], [])
        self.assertEqual(result["rejected"], [])

    def test_request_dataset_preserves_json_error_from_nonzero_request_script(self) -> None:
        class Proc:
            returncode = 1
            stderr = ""
            stdout = (
                '{"schema":"tradecat.request_result.v1","ok":false,'
                '"error":{"code":"remote_http_status","status":404}}'
            )

        with patch("tradecat_auto.tradecat_source.subprocess.run", return_value=Proc()):
            result = TradeCatPublicSource(root=".").request_dataset("event_stream", limit=5)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "remote_http_status")
        self.assertEqual(result["error"]["status"], 404)
        self.assertEqual(result["returncode"], 1)


if __name__ == "__main__":
    unittest.main()
