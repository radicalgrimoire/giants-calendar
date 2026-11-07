"use strict";

const fs = require("node:fs");
const path = require("node:path");
const ROOT = path.resolve(__dirname, "..");
const DIRECTORY = path.join(ROOT, "data", "snapshots-giants");
const ORIGIN = "https://www.giants.jp";

function isoDate(value) {
  const match = /^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:\s.*)?$/.exec(value || "");
  if (!match) throw new Error(`Invalid schedule date: ${value}`);
  const result = `${match[1]}-${match[2].padStart(2, "0")}-${match[3].padStart(2, "0")}`;
  if (new Date(`${result}T00:00:00Z`).toISOString().slice(0, 10) !== result) {
    throw new Error(`Invalid schedule date: ${value}`);
  }
  return result;
}

function safeUrl(value) {
  if (!value) return null;
  const url = new URL(value, ORIGIN);
  if (!["http:", "https:"].includes(url.protocol)) throw new Error(`Unsupported URL: ${value}`);
  return url.href;
}

function normalizeSchedule(props, month) {
  if (props?.month !== month || !Array.isArray(props.calenderDayInfo)) {
    throw new Error(`Unexpected schedule data for ${month}`);
  }
  const days = props.calenderDayInfo.map((entry) => {
    const info = entry.dayInfo;
    const date = isoDate(info?.date);
    if (date.slice(0, 7).replace("-", "") !== month || !Array.isArray(entry.buttons)) {
      throw new Error(`Unexpected schedule entry: ${date}`);
    }
    const campaigns = entry.buttons.filter(button => button.type?.startsWith("campaign"))
      .map(button => ({
        title: String(button.text || "").trim(),
        url: safeUrl(button.linkUrl || button.campaignDetail?.buttons?.find(link => link.url)?.url)
      }));
    if (campaigns.some(event => !event.title)) throw new Error(`Missing event title: ${date}`);
    const game = info.gameInfo;
    if (game) {
      if (!/^\d{8}_\d+_\d+$/.test(game.gameId || "") || !game.homeTeamName || !game.visitorTeamName) {
        throw new Error(`Incomplete game data: ${date}`);
      }
      const link = entry.buttons.find(button => button.type === "gameResult")?.linkUrl;
      const gameUrl = safeUrl(link);
      if (gameUrl && gameUrl !== `${ORIGIN}/game/${game.gameId}/`) {
        throw new Error(`Unexpected game URL: ${gameUrl}`);
      }
      return {
        date,
        game: {
          id: String(game.gameId), home: String(game.homeTeamName),
          away: String(game.visitorTeamName), status: String(game.gameStatus || ""),
          start: game.gameStartDate || null, location: game.ballparkName || null,
          home_score: game.gameStatus === "after" ? game.homeTeamTotalRuns : null,
          away_score: game.gameStatus === "after" ? game.visitorTeamTotalRuns : null,
          url: gameUrl
        },
        events: campaigns
      };
    }
    if (info.eventInfo?.title) {
      return {
        date,
        event: {
          title: String(info.eventInfo.title).trim(),
          location: String(info.eventInfo.place || "").trim(),
          url: campaigns.find(item => item.url)?.url || null
        }
      };
    }
    return { date };
  });
  const uniqueDates = new Set(days.map(day => day.date));
  const expectedDays = new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(4, 6)), 0)).getUTCDate();
  if (uniqueDates.size !== expectedDays) {
    throw new Error(`Incomplete schedule for ${month}`);
  }
  return { schema_version: 1, month, days };
}

function normalizeDetail(props, gameId) {
  const info = props?.response?.bipGameDetailResponse?.gameInfo;
  if (info?.gameScoreInfo?.gameId !== gameId) throw new Error(`Unexpected game detail: ${gameId}`);
  const end = info.gameScoreInfoSub?.gameEndDate;
  const start = info.gameScoreInfo?.gameStartDate;
  const pattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00$/;
  if (!pattern.test(start || "") || !pattern.test(end || "") || Number.isNaN(Date.parse(start)) ||
      Number.isNaN(Date.parse(end)) || Date.parse(end) <= Date.parse(start)) {
    throw new Error(`Game end time is not available: ${gameId}`);
  }
  return { id: gameId, start, end };
}

function writeJson(file, data) {
  fs.mkdirSync(DIRECTORY, { recursive: true });
  const target = path.join(DIRECTORY, file);
  const temporary = `${target}.tmp`;
  fs.writeFileSync(temporary, JSON.stringify(data, null, 2) + "\n", "utf8");
  fs.renameSync(temporary, target);
}

function readMonth(month) {
  const file = path.join(DIRECTORY, `${month}.json`);
  if (!fs.existsSync(file)) return null;
  const data = JSON.parse(fs.readFileSync(file, "utf8"));
  if (data.schema_version !== 1 || data.month !== month || !Array.isArray(data.days)) {
    throw new Error(`Invalid stored schedule: ${file}`);
  }
  return data;
}

function currentDates(now = new Date()) {
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
  const start = new Date(`${today}T00:00:00Z`);
  const yesterday = new Date(start.getTime() - 86400000).toISOString().slice(0, 10);
  const next = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 1));
  return { today, yesterday, months: [today.slice(0, 7).replace("-", ""), next.toISOString().slice(0, 7).replace("-", "")] };
}

async function fetchProps(page, url) {
  const response = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
  if (!response?.ok()) throw new Error(`Failed to fetch ${url}: HTTP ${response?.status() ?? "no response"}`);
  const text = await page.locator("script#__NEXT_DATA__").textContent({ timeout: 10000 });
  return JSON.parse(text).props.pageProps;
}

async function main() {
  const args = process.argv.slice(2);
  const values = {};
  for (let i = 0; i < args.length; i += 2) {
    if (!["--month", "--date"].includes(args[i]) || !args[i + 1] || values[args[i]]) {
      throw new Error("Usage: node fetch_giants_schedule.cjs [--month YYYYMM] [--date YYYY-MM-DD]");
    }
    values[args[i]] = args[i + 1];
  }
  const now = currentDates();
  const manual = Boolean(values["--month"] || values["--date"]);
  if (values["--date"] && !/^\d{4}-\d{2}-\d{2}$/.test(values["--date"])) throw new Error("Date must use YYYY-MM-DD");
  const date = values["--date"] ? isoDate(values["--date"]) : manual ? null : now.yesterday;
  const months = values["--month"] ? [values["--month"]] :
    values["--date"] ? [date.slice(0, 7).replace("-", "")] : now.months;
  if (!manual) {
    for (let i = months.length - 1; i >= 0; i--) {
      if (months[i] < "202701" && months[i] !== "202611") months.splice(i, 1);
    }
  }
  if (values["--month"] && date && date.slice(0, 7).replace("-", "") !== values["--month"]) {
    throw new Error("The requested month and date must match");
  }
  for (const month of months) {
    if (!/^\d{4}(0[1-9]|1[0-2])$/.test(month) || (month < "202701" && month !== "202611")) {
      throw new Error(`Unsupported month: ${month}; only November 2026 and 2027 onwards are supported`);
    }
  }
  if (date && date > now.today) throw new Error(`Cannot fetch future game details: ${date}`);
  const { chromium } = require("playwright");
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    for (const month of months) {
      const url = `${ORIGIN}/schedule/first-team/?month=${month}`;
      const data = normalizeSchedule(await fetchProps(page, url), month);
      const previous = readMonth(month);
      if (previous?.days.some(day => day.game || day.event) && !data.days.some(day => day.game || day.event)) {
        throw new Error(`Schedule unexpectedly became empty: ${month}`);
      }
      writeJson(`${month}.json`, data);
      console.log(`Saved official schedule: ${month}`);
    }
    if (date) {
      const month = date.slice(0, 7).replace("-", "");
      const stored = readMonth(month);
      if (!stored) {
        console.warn(`No saved schedule for ${date}; check manually if needed.`);
      } else {
        const games = stored.days.filter(day => day.date === date && day.game);
        for (const day of games) {
          if (!day.game.url || day.game.status !== "after") {
            console.warn(`Game detail not available for ${date}: ${day.game.id}; check manually if needed.`);
            continue;
          }
          const detail = normalizeDetail(await fetchProps(page, day.game.url), day.game.id);
          writeJson(`detail-${day.game.id}.json`, { schema_version: 1, date, ...detail });
          console.log(`Saved game end: ${day.game.id} ${detail.end}`);
        }
      }
    }
  } finally {
    await browser.close();
  }
}

module.exports = { isoDate, safeUrl, normalizeSchedule, normalizeDetail, currentDates };
if (require.main === module) main().catch(error => { console.error(error); process.exitCode = 1; });
