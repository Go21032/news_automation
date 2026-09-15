#!/usr/bin/env python3
"""
ベイカレント時事問題ログ: output.json を読み込み、
Googleスプレッドシートに「本日(JST)の日付」シートを作成/追記する。

このスクリプトは「思考」を含まない決定的な処理のみを行う
(ニュース収集・回答例生成はClaude Code側の責務)。

シートレイアウト(1シート=1日、縦2段組み):

    A1: #ニュース                                  (タイトル行, A:E結合)
    A2: 軸 | 見出し | リンク | 媒体 | 要約           (ニュース見出し行)
    A3〜: レコード分の「ニュース」データ行
    (空白2行)
    A(5+N): #回答                                   (タイトル行, A:E結合)
    A(6+N): 立場 | 理由1 | 理由2 | 反論と返し | コンサル視点 (回答見出し行)
    A(7+N)〜: レコード分の「回答」データ行
    ※ N = そのシートに書き込まれているレコード件数

ニュース行と回答行は同じ相対インデックス(i番目)で対応する。
再実行時は既存の2ブロックからレコードを復元し、新規分をマージした上で
シート全体を作り直す(件数が変わるとブロックの開始行も変わるため)。

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
JST = timezone(timedelta(hours=9))

NEWS_TITLE = "#ニュース"
ANSWER_TITLE = "#回答"
NEWS_HEADER = ["軸", "見出し", "リンク", "媒体", "要約"]
ANSWER_HEADER = ["立場", "理由1", "理由2", "反論と返し", "コンサル視点"]
N_COLS = 5  # A〜E
LAST_COL = chr(ord("A") + N_COLS - 1)  # "E"

# ニュース/回答ブロックを視覚的に区別するための配色
TITLE_BG = {"red": 0.20, "green": 0.20, "blue": 0.20}
TITLE_FG = {"red": 1.0, "green": 1.0, "blue": 1.0}
NEWS_HEADER_BG = {"red": 0.79, "green": 0.85, "blue": 0.97}    # 薄い青(ニュース)
ANSWER_HEADER_BG = {"red": 0.85, "green": 0.93, "blue": 0.83}  # 薄い緑(回答)


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


def normalize(r: dict) -> dict:
    """output.json のキーゆれを吸収し、内部共通スキーマに正規化する。"""
    return {
        "軸": r.get("軸", ""),
        "見出し": r.get("見出し", ""),
        "url": r.get("url", r.get("リンク", "")),
        "媒体": r.get("媒体", ""),
        "要約": r.get("要約", ""),
        "立場": r.get("立場", ""),
        "理由1": r.get("理由1", r.get("理由①", "")),
        "理由2": r.get("理由2", r.get("理由②", "")),
        "反論と返し": r.get("反論と返し", r.get("想定反論と返し", "")),
        "コンサル視点": r.get("コンサル視点", r.get("コンサルならどう提案するか", "")),
    }


def get_or_create_sheet(sh: gspread.Spreadsheet, title: str) -> gspread.Worksheet:
    try:
        return sh.worksheet(title)
    except gspread.exceptions.WorksheetNotFound:
        return sh.add_worksheet(title=title, rows=200, cols=N_COLS + 2)


def _news_data_row_count(values: list[list[str]]) -> int:
    """3行目(index2)から始まるニュースデータの件数(最初の空行まで)を数える。"""
    count = 0
    for row in values[2:]:
        if not row or not any(cell.strip() for cell in row[:N_COLS]):
            break
        count += 1
    return count


def parse_existing_records(values: list[list[str]]) -> list[dict]:
    """既存シートの2段組みレイアウトを record dict のリストに復元する
    (再実行時の重複検知・マージ用)。"""
    if len(values) < 3:
        return []
    n = _news_data_row_count(values)
    if n == 0:
        return []

    news_rows = values[2:2 + n]

    answer_header_row_idx = None
    for i, row in enumerate(values):
        if row and row[0].strip() == "立場":
            answer_header_row_idx = i
            break

    answer_rows: list[list[str]] = []
    if answer_header_row_idx is not None:
        answer_rows = values[answer_header_row_idx + 1: answer_header_row_idx + 1 + n]

    records = []
    for i in range(n):
        news = list(news_rows[i]) if i < len(news_rows) else []
        ans = list(answer_rows[i]) if i < len(answer_rows) else []
        news += [""] * (N_COLS - len(news))
        ans += [""] * (N_COLS - len(ans))
        records.append({
            "軸": news[0], "見出し": news[1], "url": news[2], "媒体": news[3], "要約": news[4],
            "立場": ans[0], "理由1": ans[1], "理由2": ans[2], "反論と返し": ans[3], "コンサル視点": ans[4],
        })
    return records


def answer_title_row(n: int) -> int:
    """レコード件数nに対する回答ブロックのタイトル行(1-indexed)。"""
    return 5 + n


def build_grid(records: list[dict]) -> list[list[str]]:
    n = len(records)
    total_rows = 6 + 2 * n
    grid: list[list[str]] = [["" for _ in range(N_COLS)] for _ in range(total_rows)]

    grid[0][0] = NEWS_TITLE
    grid[1] = NEWS_HEADER[:]
    for i, r in enumerate(records):
        grid[2 + i] = [r["軸"], r["見出し"], r["url"], r["媒体"], r["要約"]]

    at_row = answer_title_row(n)  # 1-indexed
    grid[at_row - 1][0] = ANSWER_TITLE
    grid[at_row] = ANSWER_HEADER[:]
    for i, r in enumerate(records):
        grid[at_row + 1 + i] = [
            r["立場"], r["理由1"], r["理由2"], r["反論と返し"], r["コンサル視点"],
        ]
    return grid


def apply_formatting(ws: gspread.Worksheet, n: int) -> None:
    at_row = answer_title_row(n)

    def band(row: int) -> str:
        return f"A{row}:{LAST_COL}{row}"

    def banner(row: int) -> None:
        rng = band(row)
        ws.format(rng, {
            "backgroundColor": TITLE_BG,
            "textFormat": {"bold": True, "foregroundColor": TITLE_FG},
        })
        try:
            ws.merge_cells(rng)
        except Exception:
            pass  # 結合に失敗しても書き込み自体は継続する

    def header(row: int, bg: dict) -> None:
        ws.format(band(row), {"backgroundColor": bg, "textFormat": {"bold": True}})

    banner(1)
    header(2, NEWS_HEADER_BG)
    banner(at_row)
    header(at_row + 1, ANSWER_HEADER_BG)

    if n > 0:
        news_data_rng = f"A3:{LAST_COL}{2 + n}"
        answer_data_rng = f"A{at_row + 2}:{LAST_COL}{at_row + 1 + n}"
        for rng in (news_data_rng, answer_data_rng):
            ws.format(rng, {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"})


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
    existing_records = parse_existing_records(existing_values)
    existing_headlines = {r["見出し"] for r in existing_records if r["見出し"]}

    new_records = load_records(json_path)
    if not new_records:
        print(f"[write_to_sheet] {title} シート: output.jsonが空配列のため書き込みなし。")
        return

    merged_records = list(existing_records)
    added = 0
    skipped = 0
    for r in new_records:
        rec = normalize(r)
        headline = rec["見出し"]
        if not headline or headline in existing_headlines:
            skipped += 1
            continue
        merged_records.append(rec)
        existing_headlines.add(headline)
        added += 1

    if added == 0:
        print(f"[write_to_sheet] {title} シート: 新規追加なし (重複または0件、スキップ {skipped} 件)。")
        return

    grid = build_grid(merged_records)

    # 件数が変わるとブロック開始行がずれるため、都度シート全体を作り直す。
    # 古い結合セル(#ニュース/#回答タイトル行)が残っていると新しい行位置と
    # 衝突する可能性があるため、書き込み前に全結合を解除しておく。
    try:
        sh.batch_update({
            "requests": [{"unmergeCells": {"range": {"sheetId": ws.id}}}]
        })
    except Exception:
        pass  # 結合が存在しない場合などはそのまま続行
    ws.clear()
    ws.resize(rows=len(grid), cols=N_COLS)
    ws.update(range_name="A1", values=grid, value_input_option="USER_ENTERED")
    apply_formatting(ws, len(merged_records))

    print(
        f"[write_to_sheet] {title} シートに {added} 件を追記しました "
        f"(重複/空見出しでスキップ: {skipped} 件、合計 {len(merged_records)} 件)。"
    )


if __name__ == "__main__":
    main()
