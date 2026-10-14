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
- 回戦数は年と対戦カードごとに、日付順で付与します。得点付きの試合を重複なく数え、セ・リーグ各5球団との25試合ずつ、パ・リーグ各6球団との3試合ずつ（計143試合）の消化を確認できた場合、その後の試合をクライマックスシリーズとして `【CS】読売ジャイアンツ vs 横浜DeNAベイスターズ 第1戦` 形式で付与します。CSの戦数は通常の回戦数とは別に対戦カードごとに数えます。消化を確認できない場合は通常の表記を維持し、全カードの消化前に特定カードが規定試合数を超えた場合は警告を出します。
- ジャイアンツ主催試合の場所には `東京ドーム` を設定します。地方開催日は `data/local-stadium.env` に `YYYY-MM-DD=球場名` を追記すると、JST の試合日で照合してその球場名を優先設定します。空行と `#` から始まるコメント行は無視します。

## NPB日程からの補完

公式Google Calendarにない期間は、GitHub Actions の **Import NPB schedule** を手動実行し、NPB日程詳細ページのHTTPS URLを `source_url` に入力します。ワークフローはHTMLを保存し、Geminiに巨人戦だけをJSONへ抽出させ、日付・時刻・チーム・得点を検証してから年度別スナップショットへマージします。`data/games.json` と `giants.ics` はこのワークフローでは更新せず、既存の定時生成で更新します。

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

## 今後のデータ方針（引き継ぎ用）

現在のGoogle Calendarを主な情報源とする方式では、試合結果の反映遅延または未反映により、終了後も得点のない予定が残ることがあります。生成処理は得点のない過去予定を配信対象から除外するため、この状態では試合が `data/games.json` と `giants.ics` から消えます。

今後は、**NPB公式の日程詳細ページを試合データの正本**、Google Calendarを予定の補足情報とする構成へ移行する。

```text
NPB公式の日程詳細HTML
  -> Geminiによる全12球団・全試合の統一JSON抽出
  -> 検証済みの年度別NPBスナップショット（正本）
  -> 読売ジャイアンツ戦だけを抽出
  -> data/games.json / giants.ics

Google Calendar
  -> NPB正本にない予定の補足
```

### 統合の優先順位

同一試合は、日付・ホームチーム・ビジターチームをキーとして照合する。チーム名は各情報源の表記を正規化して比較し、開始時刻が変更されても同一試合として扱う。NPBの得点付き結果を最優先とし、Google由来の得点なし予定で上書きしてはならない。

```text
NPB（得点あり） > Google（得点あり） > Google（得点なし）
```

NPB結果を取り込んだ際は、同一試合のGoogle由来イベントを得点付きNPBイベントで置換する。以後のGoogleカレンダー取得時も、NPB結果と一致するGoogle由来イベントは取り込まない。

### Gemini出力の検証要件

GeminiはNPB HTMLの表記揺れを統一JSONへ変換する役割に限定し、出力を無検証で正本にしてはならない。少なくとも次を検証する。

- 日付・開始時刻・得点の形式と値
- 12球団のチーム名への正規化、およびホームとビジターの相違
- 同一試合の重複
- 日ごとの試合数が6試合以下であること
- HTML上の試合数と抽出JSONの件数が一致すること
- 既存の確定結果・試合が不自然に消えないこと

全試合JSONは過去シーズン分も保持する。配信用ICSはジャイアンツ戦だけを抽出するため、正本データを全12球団分に拡張しても、購読用 `giants.ics` の容量は大きく増えない。