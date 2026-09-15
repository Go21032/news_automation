# ベイカレント時事問題 自動収集ワークフロー セットアップ手順

毎朝8:00(JST)にGitHub Actionsが起動し、Claude Code(Sonnet/Opus、契約中のPro/Maxのサブスク利用枠)が
4軸のニュースを収集・回答例を生成し、Pythonスクリプトが本日日付のシートをGoogleスプレッドシートに作成して書き込みます。

設計の背景・全体像は Vault側のノート
[[就活/ベイカレント/ベイカレント時事問題対策]] の「6. 自動化（GitHub Actions + Claude Code）」を参照してください。

## 0. 前提

- GitHubアカウント（この`automation/`フォルダの中身をリポジトリのルートとしてpushする。Private推奨）
- Google Cloudプロジェクト（サービスアカウント作成用）
- Claude Pro または Max プラン契約
- ローカルに `claude` CLI（Claude Code）がインストール済みでログイン可能なこと

## 1. リポジトリを作成してpush

```bash
# このフォルダの中身（.github/, PROMPT.md, scripts/, README.md）を
# 新規GitHubリポジトリのルートに配置してpushする
git init
git add .
git commit -m "init: baycurrent daily news automation"
git branch -M main
git remote add origin git@github.com:<your-account>/baycurrent-news-bot.git
git push -u origin main
```

## 2. Googleスプレッドシート側の準備

1. Google Sheetsで新規スプレッドシートを作成し、名前を「ベイカレント時事問題ログ」等にする。
2. URLから **スプレッドシートID** を控える
   （`https://docs.google.com/spreadsheets/d/【ここがID】/edit`）。

## 3. Google Cloud: サービスアカウント発行

1. Google Cloud Console で任意のプロジェクトを用意し、**Google Sheets API** を有効化。
2. 「APIとサービス」→「認証情報」→ サービスアカウントを新規作成。
3. 作成したサービスアカウントの「鍵」タブから **JSON形式の鍵をダウンロード**（例: `sa.json`）。
4. サービスアカウントのメールアドレス（`xxxx@xxxx.iam.gserviceaccount.com`）を、
   手順2で作ったスプレッドシートに**編集者として共有**する（スプレッドシート右上の「共有」）。
5. JSONをBase64エンコードする。

   ```bash
   # macOS/Linux
   base64 -w0 sa.json

   # Windows PowerShell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("sa.json"))
   ```

## 4. Claude Code のOAuthトークン発行（サブスク利用）

```bash
claude setup-token
```

ブラウザでPro/Maxアカウントにログインし、発行されたトークンをコピーする。
このトークンはAPI従量課金ではなく、契約プランの利用上限（5時間/週次の使用枠）を消費する。

## 5. GitHub Secretsの登録

リポジトリの Settings → Secrets and variables → Actions → New repository secret で以下を登録。

| Secret名 | 値 |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | 手順4で発行したトークン |
| `GOOGLE_SA_JSON_BASE64` | 手順3-5でBase64化したサービスアカウントJSON |
| `SPREADSHEET_ID` | 手順2で控えたスプレッドシートID |

## 6. 動作確認

1. GitHubリポジトリの「Actions」タブ → 「Baycurrent Daily News Digest」→「Run workflow」で手動実行。
2. 実行ログでClaude Codeの収集結果、`write_to_sheet.py`の出力を確認。
3. スプレッドシートに本日日付のシートが作成され、記事一覧と回答例が書き込まれていることを確認。
4. 問題なければ、翌朝8時台の自動実行を待つ。

## 7. 運用上の注意

- **schedule実行の精度**：GitHub Actionsの`cron`はUTC基準・実行開始が数分〜数十分遅延することがある。「8:00ちょうど」ではなく「8時台」の精度と考える。
- **60日ルール**：GitHubの無料枠では60日間コミットがないとscheduleトリガーが自動停止する。月1回程度のダミーコミットか手動実行で生存確認するとよい。
- **claude-code-actionの仕様変更**：`.github/workflows/daily-news.yml`内の`with:`パラメータ名は
  [anthropics/claude-code-action](https://github.com/anthropics/claude-code-action) の最新READMEと突き合わせて確認すること。
- **東洋経済オンラインの有料記事**：Claude Codeには「無料記事のみ対象」と指示済みだが、有料壁で本文が取得できない場合は自動的にスキップされる想定。
- **重複防止**：`write_to_sheet.py`は同一シート内で「見出し」が完全一致する行はスキップする。表記ゆれ（記号の有無等）までは検知しないため、気になる場合はシートを目視確認する。

## 8. ローカルでの単体テスト（Claude Codeを介さない場合）

`write_to_sheet.py`単体の動作確認をしたい場合、手動で`output.json`を用意して実行できる。

```bash
export GOOGLE_APPLICATION_CREDENTIALS=./sa.json
export SPREADSHEET_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
pip install -r scripts/requirements.txt
python scripts/write_to_sheet.py output.json
```

`output.json`のサンプル:

```json
[
  {
    "軸": "①AI・技術×雇用",
    "見出し": "サンプル記事の見出し",
    "url": "https://www.itmedia.co.jp/business/articles/xxxx/xx/news001.html",
    "媒体": "ITmediaビジネスオンライン",
    "要約": "生成AIの業務導入により一部業務が自動化されるという内容。",
    "立場": "賛成",
    "理由1": "業務効率化により人的リソースを高付加価値業務へ再配分できる",
    "理由2": "一方で該当業務従事者の再教育・再配置が必要になる",
    "反論と返し": "雇用減少への懸念に対しては、リスキリング支援策とセットで導入することで緩和できる",
    "コンサル視点": "導入ロードマップと並行して従業員向け移行支援プログラムを設計すべき"
  }
]
```
