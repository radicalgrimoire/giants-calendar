# Giants Calendar

読売ジャイアンツの公式 Google Calendar を加工し、対戦カードと回戦数を付けた購読用 ICS カレンダーです。

## Google Calendar への追加

Google Calendar の「他のカレンダー」から「URL で追加」を選び、次の URL を登録します。

```text
https://raw.githubusercontent.com/radicalgrimoire/giants-calendar/main/giants.ics
```

Google 側が URL を定期取得するため、ICS ファイルの更新は後から反映されます。反映時刻は Google Calendar に依存し、即時ではありません。

## 更新ルール

- 毎日 09:10 JST に公式カレンダーを取得し、`giants.ics` を全量再生成します。
- 月曜日に取得した原本は `data/source/YYYY-MM-DD.ics` として保存します。
- `away @ home` の予定タイトルを解析し、ホームチームを先にした `広島東洋カープ 対 読売ジャイアンツ 16回戦` 形式へ置き換えます。
- 回戦数は年と対戦カードごとに、日付順で付与します。

ローカルで実行する場合は、Python 3.11 以降で次を実行します。

```powershell
py -m pip install -r requirements.txt
py scripts/generate_calendar.py
```