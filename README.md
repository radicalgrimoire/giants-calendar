# Giants Calendar

読売ジャイアンツの試合日程を購読できるカレンダーです。対戦カード、回戦数、試合結果を表示します。

## Google Calendar への追加

Google Calendar の「他のカレンダー」から「URL で追加」を選び、次の URL を登録してください。

```text
https://raw.githubusercontent.com/radicalgrimoire/giants-calendar/main/giants.ics
```

カレンダーには過去の試合も含まれます。予定は3月1日から11月1日まで原則毎日自動更新されますが、Google Calendar への反映には時間がかかる場合があります。開始時刻が未定の試合は終日予定として表示され、予備日は含まれません。中止情報もこの期間に確認するため、反映まで時間がかかる場合があります。

試合日程は変更される場合があります。最新情報は[読売ジャイアンツ公式サイト](https://www.giants.jp/game/)などをご確認ください。

## Google カレンダーへの自動同期

Google Cloud で Google Calendar API を有効にし、サービスアカウントを作成します。同期先カレンダーをそのサービスアカウントのメールアドレスと「予定の変更」権限で共有してください。サービスアカウントの JSON 鍵全体を GitHub リポジトリの **Settings → Secrets and variables → Actions → New repository secret** に `GIANTS_CALENDER_API` という名前で登録します（`CALENDER` の綴りで登録したSecret名に合わせています）。

同じ Actions 設定の **Variables** タブで `GIANTS_CALENDAR_ID` を作成し、Google カレンダーの「設定と共有」→「カレンダーの統合」にあるカレンダーIDを値に設定してください。Workflowは毎日1回実行し、シーズン中はICSを更新してから、シーズン外は既存ICSを使ってGoogle Calendar APIで予定を追加・更新します。ICSからなくなった同期済み予定は削除します。サービスアカウントの JSON 鍵は公開せず、GitHub Secretにのみ保存してください。

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
