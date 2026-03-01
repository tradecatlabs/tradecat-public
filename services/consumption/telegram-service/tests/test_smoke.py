from pathlib import Path


def test_bot_app_no_sqlite_signal_wording():
    app_py = Path(__file__).resolve().parents[1] / "src" / "bot" / "app.py"
    text = app_py.read_text(encoding="utf-8")

    # 迁移完成后不应再出现 SQLite 相关误导文案/分支
    assert "SQLite信号" not in text
    assert "start_pg_signal_loop" not in text
