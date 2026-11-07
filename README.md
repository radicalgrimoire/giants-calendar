# Giants Calendar

読売ジャイアンツの試合日程を購読できるカレンダーです。対戦カード、回戦数、試合結果を表示します。

## Google Calendar への追加

Google Calendar の「他のカレンダー」から「URL で追加」を選び、次の URL を登録してください。

```text
https://raw.githubusercontent.com/radicalgrimoire/giants-calendar/main/giants.ics
```

カレンダーには過去の試合も含まれます。予定は3月1日から11月1日まで原則毎日自動更新されますが、Google Calendar への反映には時間がかかる場合があります。開始時刻が未定の試合は終日予定として表示され、予備日は含まれません。中止情報もこの期間に確認するため、反映まで時間がかかる場合があります。

試合日程は変更される場合があります。最新情報は[読売ジャイアンツ公式サイト](https://www.giants.jp/game/)などをご確認ください。

ICS は iCalendar の仕様に合わせて CRLF で生成します。Git の改行変換は無効にし、配信用・アーカイブともに保存時の CRLF を維持します。

## 球団公式の日程取得テスト

GitHub Actions の「Probe Giants schedule」は、Playwright で球団公式の日程ページを開き、指定月（`YYYYMM`）のイベント名をログに表示する手動実行用のテストです。ICS や Google カレンダーは更新しません。取得できない場合やデータ形式が変わった場合は失敗します。

## 球団公式の日程と試合詳細

日次更新では球団公式の一軍日程ページを当月と翌月の各1回取得し、`data/snapshots-giants/` に保存します。2026年は試験用の10月3日と11月、2027年以降は対象月を取り込みます。試合日のイベント名と詳細リンクは試合予定の詳細欄に追加し、試合詳細へのリンクも掲載します。キャンプや休養日など、試合のない日の球団イベントは終日予定として追加します。既存のNPB・Google提供カレンダーの取得と試合結果表示は維持します。

`data/local-url.env` には `元URL = 差し替え先URL` の形式でURLを1行ずつ設定できます（`=` の前後に空白が必要）。球団公式の試合詳細・試合日のイベント・試合のない日のイベントに含まれるURLが完全一致した場合、カレンダー生成時のみ差し替えます。ファイルがない場合は差し替えません。不正な設定や元URLの重複はエラーになります。2026年秋季キャンプの詳細ページはiPhoneで開けない場合があるため、記事一覧のURLを指定しています。取得したスナップショットは変更しません。

前日の試合詳細も1回確認し、終了時刻が掲載されていれば既存予定の終了時刻を更新します。試合開始時刻が未定だった場合は公式の開始時刻も使用します。確認できるまでは従来の仮の終了時刻を使います。取得に失敗しても既存のデータを保持し、日次の他の更新を行ったうえでワークフローにエラーを表示します。過去の試合を自動で再取得しません。

「Update Giants calendar」を手動実行するとき、`month` に `YYYYMM` を指定するとその月の日程だけを取得します。`game_date` に `YYYY-MM-DD` を指定すると、その月の日程と指定日の試合詳細を取得します。両方を指定する場合は同じ月にしてください。どちらも省略すると通常の日次更新を実行します。定期更新の期間は従来どおり3月1日から11月1日までです。

対象テストは `node --test scripts/test_fetch_giants_schedule.cjs` と `python -m unittest discover -s scripts -p "test_*.py"` で実行できます。

## Google カレンダーへの自動同期

Google Cloud で Google Calendar API を有効にし、サービスアカウントを作成します。同期先カレンダーをそのサービスアカウントのメールアドレスと「予定の変更」権限で共有してください。サービスアカウントの JSON 鍵全体を GitHub リポジトリの **Settings → Secrets and variables → Actions → New repository secret** に `GIANTS_CALENDER_API` という名前で登録します（`CALENDER` の綴りで登録したSecret名に合わせています）。

同じ Actions 設定の **Variables** タブで `GIANTS_CALENDAR_ID` を作成し、Google カレンダーの「設定と共有」→「カレンダーの統合」にあるカレンダーIDを値に設定してください。日程更新Workflowの完了後に、別の同期WorkflowがGoogle Calendar APIで予定を追加・更新します。日程更新がない日も既存ICSで同期し、ICSからなくなった同期済み予定は削除します。同期WorkflowはActionsから手動実行することもできます。サービスアカウントの JSON 鍵は公開せず、GitHub Secretにのみ保存してください。

同期先をGoogleカレンダーとして一般公開する場合は、Google カレンダーの「設定と共有」→「アクセス権限」で一般公開を有効にし、「カレンダーの統合」から公開URLを取得してください。

## 2027年の関東ビジター戦

依存パッケージを `pip install -r requirements.txt` でインストールし、次のコマンドを実行すると、公開カレンダーから対象試合を一覧表示します。

```powershell
python scripts\weekend_away_games.py
```

全曜日の関東1都6県の試合が対象で、東京ドームと中止試合は除きます。対象試合は平日と土日祝日に分けて表示し、祝日・休日には[内閣府のCSV](https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv)を使用します。球場の住所に都道府県名がない場合や対戦カードを判定できない場合は警告を表示します。ローカルのICSを使う場合は `--ics giants.ics`、ダウンロード済みの内閣府のCSVを使う場合は `--holidays <CSVファイル>` を指定してください。

## 2027年の相手球団別試合数

次のコマンドで、ホーム・ビジターを問わず、相手球団別に平日（月〜金の祝日・休日を除く）と週末＋祝日（土日または祝日・休日）の試合数を集計します。祝日と週末が重なっても二重には数えず、中止試合は除きます。祝日・休日は[内閣府のCSV](https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv)を使用します。

```powershell
python scripts\count_games_by_opponent.py
```

ローカルのICSを使う場合は `--ics giants.ics`、ダウンロード済みの内閣府のCSVを使う場合は `--holidays <CSVファイル>` を指定してください。対戦相手を判定できない試合は警告を表示して集計から除きます。
