# Giants Calendar

読売ジャイアンツの公式 Google Calendar を加工し、対戦カードと回戦数を付けた購読用 ICS カレンダーです。

## Google Calendar への追加

Google Calendar の「他のカレンダー」から「URL で追加」を選び、次の URL を登録します。

```text
https://raw.githubusercontent.com/radicalgrimoire/giants-calendar/main/giants.ics
```

Google 側が URL を定期取得するため、ICS ファイルの更新は後から反映されます。反映時刻は Google Calendar に依存し、即時ではありません。

## 更新ルール

- 毎日 12:00 JST に公式カレンダーを取得し、試合の年度ごとに `data/snapshots/snapshot-giants-YYYY.json` へマージします。公式から消えた予定も削除せず、スナップショットに保持し続けます。
- 毎日 16:00 JST に当年のスナップショットから `data/games.json` を更新し、`giants.ics` を全量再生成します。
- `data/games.json` は当年のスナップショットを元に生成します。過去日時で得点情報のない予定は、中止または不成立の可能性があるため除外します。
- `giants.ics` は当年の試合だけを収録します。毎年 1 月 1 日に前年のファイルを `backlog/giants-YYYY.ics` として退避し、新しい年のカレンダーを生成します。
- `away @ home` の予定タイトルを解析し、ホームチームを先にした `広島東洋カープ vs 読売ジャイアンツ 16回戦` 形式へ置き換えます。パ・リーグとの対戦には `【交流戦】` を付け、終了済み試合にはホーム・ビジター順の得点を `（2 - 8）` として末尾へ追加します。
- 回戦数は年と対戦カードごとに、日付順で付与します。
- ジャイアンツ主催試合の場所には `東京ドーム` を設定します。地方開催日は `data/local-stadium.env` に `YYYY-MM-DD=球場名` を追記すると、JST の試合日で照合してその球場名を優先設定します。空行と `#` から始まるコメント行は無視します。

## NPB日程からの補完

公式Google Calendarにない期間は、GitHub Actions の **Import NPB schedule** を手動実行し、NPB日程詳細ページのHTTPS URLを `source_url` に入力します。ワークフローはHTMLを保存し、Geminiに巨人戦だけをJSONへ抽出させ、日付・時刻・チーム・得点を検証してから年度別スナップショットへマージします。その後、`data/games.json` と `giants.ics` を再生成してコミットします。

リポジトリのActions secretに `GEMINI_APIKEY` が必要です。たとえば2026年3月分は次のURLです。

```text
https://npb.jp/games/2026/schedule_03_detail.html
```

Geminiを呼ばずに、保存済みのJSONを検証して取り込む場合は次を実行します。

```powershell
py scripts/import_npb_schedule.py --games-json data/npb-schedule-games.json
```

ローカルで実行する場合は、Python 3.11 以降で次を実行します。

```powershell
py -m pip install -r requirements.txt
py scripts/generate_calendar.py
```