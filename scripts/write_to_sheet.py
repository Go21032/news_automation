#!/usr/bin/env python3
"""
ベイカレント時事問題ログ: output.json を読み込み、
Googleスプレッドシートに「本日(JST)の日付」シートを作成/追記する。

このスクリプトは「思考」を含まない決定的な処理のみを行う
(ニュース収集・回答例生成はClaude Code側の責務)。

Usage:
    python write_to_sheet.py output.json

必要な環境変数:
    GOOGLE_APPLICATION_CREDENTIALS  サービスアカウントJSONキーのパス
    SPREADSHEET_ID                  書き込み先スプレッドシートのID
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
HEADER = [
    "軸", "見出し", "リンク", "媒体", "要約",
    "立場", "理由1", "理由2", "反論と返し", "コンサル視点",
]
JST = timezone(timedelta(hours=9))


def jst_today() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def load_records(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "items" in data:
        data = data["items"]
    if not isinstance(data, list):
        raise ValueError("output.json はレコードの配列(またはitemsキー)である必要があります")
    return data


def get_or_create_sheet(sh: gspread.Spreadsheet, title: str) -> gspread.Worksheet:
    try:
        return sh.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=200, cols=len(HEADER) + 2)
        ws.append_row(HEADER)
        return ws


def record_to_row(r: dict) -> list[str]:
    return [
        r.get("軸", ""),
        r.get("見出し", ""),
        r.get("url", r.get("リンク", "")),
        r.get("媒体", ""),
        r.get("要約", ""),
        r.get("立場", ""),
        r.get("理由1", r.get("理由①", "")),
        r.get("理由2", r.get("理由②", "")),
        r.get("反論と返し", r.get("想定反論と返し", "")),
        r.get("コンサル視点", r.get("コンサルならどう提案するか", "")),
    ]


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: write_to_sheet.py <output.json>", file=sys.stderr)
        sys.exit(1)

    json_path = sys.argv[1]
    sa_path = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    spreadsheet_id = os.environ["SPREADSHEET_ID"]

    creds = Credentials.from_service_account_file(sa_path, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(spreadsheet_id)

    title = jst_today()
    ws = get_or_create_sheet(sh, title)

    existing_values = ws.get_all_values()
    existing_headlines = {row[1] for row in existing_values[1:] if len(row) > 1}

    records = load_records(json_path)
    if not records:
        print(f"[write_to_sheet] {title} シート: output.jsonが空配列のため書き込みなし。")
        return

    rows_to_add = []
    skipped = 0
    for r in records:
        headline = r.get("見出し", "")
        if not headline or headline in existing_headlines:
            skipped += 1
            continue
        rows_to_add.append(record_to_row(r))
        existing_headlines.add(headline)

    if rows_to_add:
        ws.append_rows(rows_to_add, value_input_option="USER_ENTERED")
        print(
            f"[write_to_sheet] {title} シートに {len(rows_to_add)} 件を追記しました "
            f"(重複/空見出しでスキップ: {skipped} 件)。"
        )
    else:
        print(f"[write_to_sheet] {title} シート: 新規追加なし (重複または0件、スキップ {skipped} 件)。")


if __name__ == "__main__":
    main()
