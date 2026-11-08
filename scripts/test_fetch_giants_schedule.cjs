const test = require("node:test");
const assert = require("node:assert/strict");
const { normalizeSchedule, normalizeDetail, currentDates } = require("./fetch_giants_schedule.cjs");

function month() {
  return {
    month: "202611",
    calenderDayInfo: Array.from({ length: 30 }, (_, i) => ({
      dayInfo: { date: `2026/11/${i + 1}` }, buttons: []
    }))
  };
}

test("extracts camp, rest, games, campaign links and validates month", () => {
  const props = month();
  props.calenderDayInfo[0].dayInfo.eventInfo = { title: "秋季キャンプ", place: "G球場" };
  props.calenderDayInfo[0].buttons = [{ type: "campaignButtonLink", text: "詳細", linkUrl: "/camp/" }];
  props.calenderDayInfo[1].dayInfo.eventInfo = { title: "休養日" };
  props.calenderDayInfo[2] = {
    dayInfo: { date: "2026-11-3 14:00:00", gameInfo: {
      gameId: "20261103_8003_1", homeTeamName: "巨人", visitorTeamName: "阪神",
      gameStatus: "after", homeTeamTotalRuns: 4, visitorTeamTotalRuns: 3
    } },
    buttons: [
      { type: "gameResult", linkUrl: "/game/20261103_8003_1/" },
      { type: "campaignWithModal", text: "イベント", campaignDetail: { buttons: [{ url: "https://example.com/" }] } },
      { type: "campaignWithModal", text: "リンクなし", campaignDetail: { buttons: [] } }
    ]
  };
  const result = normalizeSchedule(props, "202611");
  assert.equal(result.days[0].event.url, "https://www.giants.jp/camp/");
  assert.equal(result.days[1].event.title, "休養日");
  assert.equal(result.days[2].game.url, "https://www.giants.jp/game/20261103_8003_1/");
  assert.deepEqual(result.days[2].events.map(e => e.url), ["https://example.com/", null]);
  assert.throws(() => normalizeSchedule(props, "202612"), /Unexpected/);
  props.calenderDayInfo.pop();
  assert.throws(() => normalizeSchedule(props, "202611"), /Incomplete/);
});

test("validates the specific game and its actual end time", () => {
  const props = { response: { bipGameDetailResponse: { gameInfo: {
    gameScoreInfo: {
      gameId: "20261103_8003_1", gameStartDate: "2026-11-03T14:00:00+09:00",
      homeStarterPitcherName: "井上 温大", visitorStarterPitcherName: "島田 舜也"
    },
    gameScoreInfoSub: { gameEndDate: "2026-11-03T16:45:00+09:00" }
  } } } };
  assert.equal(normalizeDetail(props, "20261103_8003_1").end, "2026-11-03T16:45:00+09:00");
  assert.equal(normalizeDetail(props, "20261103_8003_1").home_starter, "井上 温大");
  assert.equal(normalizeDetail(props, "20261103_8003_1").away_starter, "島田 舜也");
  props.response.bipGameDetailResponse.gameInfo.gameScoreInfo.visitorStarterPitcherName = null;
  assert.equal(normalizeDetail(props, "20261103_8003_1").away_starter, null);
  props.response.bipGameDetailResponse.gameInfo.gameScoreInfo.visitorStarterPitcherName = 123;
  assert.throws(() => normalizeDetail(props, "20261103_8003_1"), /Invalid starting pitcher/);
  props.response.bipGameDetailResponse.gameInfo.gameScoreInfo.visitorStarterPitcherName = "島田 舜也";
  assert.throws(() => normalizeDetail(props, "20261104_8003_1"), /Unexpected/);
  props.response.bipGameDetailResponse.gameInfo.gameScoreInfoSub.gameEndDate = null;
  assert.throws(() => normalizeDetail(props, "20261103_8003_1"), /not available/);
});

test("uses Tokyo dates and rolls over months and years", () => {
  assert.deepEqual(currentDates(new Date("2026-12-31T15:00:00Z")), {
    today: "2027-01-01", yesterday: "2026-12-31", months: ["202701", "202702"]
  });
});
