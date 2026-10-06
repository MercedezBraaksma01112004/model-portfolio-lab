"""Daily brief for the website's "Daily brief" page.

Each weekday evening the build fetches, from public sources that need no key and allow automated reading:
  * key numbers: ASX 200, All Ordinaries, AUD/USD, S&P 500, gold, Brent oil, iron ore (indicative), Bitcoin,
    the RBA cash rate and its last change, the next RBA meeting, Australian 3 and 10 year bond yields, the US 10 year,
    CPI (headline and trimmed mean), unemployment and the wage price index, and the next ABS releases;
  * ASX announcements for every active ASX holding in the universe, plus the market's price-sensitive announcements;
  * regulatory, legal and policy updates relevant to financial advice: ASIC media releases and financial advice
    enforcement, APRA, the Treasurer and the Financial Services minister, open Treasury consultations, Federal Court
    judgments involving ASIC, the Commissioner of Taxation or superannuation, new legislative instruments, the RBA,
    the FAAA, and ATO and AFCA news (via Google News, because both sites refuse automated requests);
  * market wrap headlines (titles and links only);
  * the day's biggest moves among the universe's holdings, from the build's own price cache.

Every source is fetched on its own and fails on its own: a blocked or changed feed leaves a note on the page and in
the "sources" list, never a failed build. Output: output/brief.json and output/brief.html.

    python scripts/daily_brief.py             # fetch everything and write the page
    python scripts/daily_brief.py --no-fetch  # rewrite the page from the last output/brief.json
"""
from __future__ import annotations

import csv
import html
import io
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
BNE = ZoneInfo("Australia/Brisbane")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"   # Yahoo rate-limits unfamiliar agents
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "en-AU,en;q=0.9"})
SOURCES: list[dict] = []          # one row per source: name, url, ok, items, note
NOW = datetime.now(BNE)


def get(url: str, *, timeout: int = 25, tries: int = 2, **kw) -> requests.Response:
    last = None
    for i in range(tries):
        try:
            r = SESSION.get(url, timeout=timeout, **kw)
            if r.status_code == 200:
                return r
            last = RuntimeError(f"HTTP {r.status_code}")
        except requests.RequestException as e:
            last = e
        time.sleep(1.5 * (i + 1))
    raise last or RuntimeError("no response")


def source(name: str, url: str):
    """Decorator-style helper: run fn, record the outcome, return [] / None on failure."""
    def wrap(fn):
        def run(*a, **k):
            try:
                out = fn(*a, **k)
                n = len(out) if isinstance(out, (list, dict)) else (1 if out is not None else 0)
                SOURCES.append({"name": name, "url": url, "ok": True, "items": n, "note": ""})
                return out
            except Exception as e:  # noqa: BLE001 - every source fails on its own
                SOURCES.append({"name": name, "url": url, "ok": False, "items": 0, "note": str(e)[:160]})
                print(f"  ! {name}: {e}", file=sys.stderr)
                return None
        return run
    return wrap


def clean(text: str, limit: int = 260) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= limit else t[: limit - 1].rsplit(" ", 1)[0] + "…"


def iso(dt: datetime | date | None) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(BNE).isoformat(timespec="minutes")
    return dt.isoformat()


def parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%d/%m/%Y"):
        try:
            d = datetime.strptime(s.replace("Z", "+0000") if fmt.endswith("%z") else s, fmt)
            return d if d.tzinfo else d.replace(tzinfo=BNE if fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%d/%m/%Y") else timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def rss_items(content: bytes) -> list[dict]:
    """RSS 2.0, RSS 1.0 (RDF) and Atom, the fields the page needs."""
    root = ET.fromstring(content)
    out = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        f = {}
        for ch in it:
            n = ch.tag.split("}")[-1]
            if n == "link":
                f["link"] = ch.get("href") or (ch.text or "").strip()
            elif n in ("title", "description", "summary", "pubDate", "date", "updated", "published", "source"):
                f.setdefault(n, (ch.text or "").strip())
        f["when"] = parse_date(f.get("pubDate") or f.get("date") or f.get("published") or f.get("updated"))
        out.append(f)
    return out


# ------------------------------------------------------------------ key numbers

YAHOO = [("asx200", "ASX 200", "^AXJO", "points"), ("allords", "All Ordinaries", "^AORD", "points"), ("audusd", "AUD/USD", "AUDUSD=X", "USD"),
         ("sp500", "S&P 500", "^GSPC", "points"), ("us10y", "US 10 year yield", "^TNX", "%"), ("gold", "Gold (USD an ounce)", "GC=F", "USD"),
         ("brent", "Brent oil (USD a barrel)", "BZ=F", "USD"), ("iron", "Iron ore 62% (USD a tonne, indicative)", "TIO=F", "USD"), ("btc", "Bitcoin (AUD)", "BTC-AUD", "AUD")]


def yahoo_last_two(symbol: str) -> tuple[float, float | None, date]:
    """Latest and previous close, and the trading date (in the exchange's own time zone)."""
    try:
        r = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(symbol)}?range=10d&interval=1d").json()
    except Exception:  # noqa: BLE001 - yfinance carries Yahoo's cookie and crumb, which rescues a rate-limited request
        import yfinance as yf
        h = yf.Ticker(symbol).history(period="10d", interval="1d")["Close"].dropna()
        if h.empty:
            raise
        return float(h.iloc[-1]), (float(h.iloc[-2]) if len(h) > 1 else None), h.index[-1].date()
    res = r["chart"]["result"][0]
    ts, closes = res.get("timestamp") or [], res["indicators"]["quote"][0].get("close") or []
    pts = [(t, c) for t, c in zip(ts, closes) if c is not None]
    if not pts:
        raise RuntimeError("no closes")
    meta = res.get("meta", {})
    tz = ZoneInfo(meta.get("exchangeTimezoneName") or "Australia/Brisbane")
    last_t, last = pts[-1]
    prev = pts[-2][1] if len(pts) >= 2 else None
    price, mtime = meta.get("regularMarketPrice"), meta.get("regularMarketTime")
    # A live price counts only when it is from the last few days and from a later day than the last daily bar
    # (the iron ore future's meta price is years old, so it is ignored and the bars are used).
    if price is not None and mtime and (time.time() - mtime) < 5 * 86400 and \
            datetime.fromtimestamp(mtime, tz).date() > datetime.fromtimestamp(last_t, tz).date():
        return float(price), float(last), datetime.fromtimestamp(mtime, tz).date()
    return float(last), (float(prev) if prev is not None else None), datetime.fromtimestamp(last_t, tz).date()


def rba_table(table: str) -> tuple[list[str], list[str], list[list[str]]]:
    """(titles, series ids, data rows) from an RBA statistical table CSV."""
    text = get(f"https://www.rba.gov.au/statistics/tables/csv/{table}-data.csv").content.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    titles = next((r for r in rows if r and r[0].strip() == "Title"), [])
    ids = next((r for r in rows if r and r[0].strip() == "Series ID"), [])
    data = [r for r in rows if r and re.match(r"^\d{1,2}[-/]", r[0].strip())]
    return titles, ids, data


def rba_series(table: str, series_id: str) -> list[tuple[date, float]]:
    _, ids, data = rba_table(table)
    j = ids.index(series_id)
    out = []
    for r in data:
        if j < len(r) and r[j].strip() not in ("", "NA"):
            d = r[0].strip()
            dt = datetime.strptime(d, "%d-%b-%Y").date() if "-" in d else datetime.strptime(d, "%d/%m/%Y").date()
            out.append((dt, float(r[j])))
    if not out:
        raise RuntimeError(f"{series_id}: no data")
    return out


def abs_latest(url: str, filters: dict | None = None) -> list[tuple[str, float]]:
    text = get(url, headers={"Accept": "text/csv"}).text
    rows = [r for r in csv.DictReader(io.StringIO(text)) if all(r.get(k) == v for k, v in (filters or {}).items())]
    pts = sorted((r["TIME_PERIOD"], float(r["OBS_VALUE"])) for r in rows if r.get("OBS_VALUE"))
    if not pts:
        raise RuntimeError("no observations")
    return pts


def fmt_period(p: str) -> str:
    m = re.match(r"(\d{4})-(\d{2})$", p)
    if m:
        return date(int(m[1]), int(m[2]), 1).strftime("%B %Y")
    m = re.match(r"(\d{4})-Q(\d)$", p)
    if m:
        return {"1": "March", "2": "June", "3": "September", "4": "December"}[m[2]] + f" quarter {m[1]}"
    return p


def key_numbers() -> tuple[list[dict], dict]:
    nums: list[dict] = []
    extra: dict = {}

    def add(key, label, value, prev=None, unit="", as_of=None, src="", note="", decimals=2, group="Markets"):
        ch = (value - prev) if (value is not None and prev is not None) else None
        nums.append({"key": key, "label": label, "value": value, "prev": prev, "change": ch,
                     "change_pct": (ch / prev * 100) if (ch is not None and prev not in (None, 0) and unit not in ("%",)) else None,
                     "unit": unit, "as_of": iso(as_of) if as_of else None, "source": src, "note": note, "decimals": decimals, "group": group})

    yv = {}
    for key, label, sym, unit in YAHOO:
        @source(f"Yahoo Finance {sym}", f"https://finance.yahoo.com/quote/{sym}")
        def one(sym=sym):
            return yahoo_last_two(sym)
        got = one()
        if got:
            v, p, t = got
            yv[key] = (v, p, t)
            note = "Front-month futures settlement; treat as indicative" if key == "iron" else ""
            add(key, label, v, p, unit, t, "Yahoo Finance", note, 4 if key == "audusd" else (3 if key == "us10y" else 2),
                "Markets" if key in ("asx200", "allords", "sp500", "audusd", "btc") else "Commodities and rates")
    if "gold" in yv and "audusd" in yv:
        g, gp, t = yv["gold"]; a, ap, _ = yv["audusd"]
        add("gold_aud", "Gold (AUD an ounce)", g / a, (gp / ap) if (gp and ap) else None, "AUD", t, "Calculated: gold in USD divided by AUD/USD", "", 0, "Commodities and rates")

    @source("RBA cash rate target (table F1)", "https://www.rba.gov.au/statistics/tables/#interest-rates")
    def cash():
        s = rba_series("f1", "FIRMMCRTD")
        return s
    s = cash()
    if s:
        add("cash_rate", "RBA cash rate target", s[-1][1], None, "%", s[-1][0], "Reserve Bank of Australia, table F1", "", 2, "Australian economy")

    @source("RBA cash rate changes (table A2)", "https://www.rba.gov.au/statistics/cash-rate/")
    def changes():
        _, ids, data = rba_table("a2")
        jc, jn = ids.index("ARBAMPCCCR"), ids.index("ARBAMPCNCRT")
        rows = []
        for r in data:
            try:   # early rows hold ranges such as "-0.50 to -1.00"; only plain numbers are wanted
                rows.append((datetime.strptime(r[0].strip(), "%d-%b-%Y").date(), float(r[jc]), float(r[jn])))
            except (ValueError, IndexError):
                continue
        return [x for x in rows if x[1] != 0]
    ch = changes()
    if ch:
        d, c, n = ch[-1]
        extra["last_rate_change"] = {"date": d.isoformat(), "change": c, "new_rate": n}
        if nums and nums[-1]["key"] == "cash_rate":
            nums[-1]["note"] = f"Last change {d.strftime('%d %B %Y')}: {'up' if c > 0 else 'down'} {abs(c):.2f} to {n:.2f}%"

    @source("RBA board meeting schedule", "https://www.rba.gov.au/schedules-events/board-meeting-schedules.html")
    def meetings():
        t = get("https://www.rba.gov.au/schedules-events/board-meeting-schedules.html").text
        out = []
        for year, body in re.findall(r"<caption[^>]*>\s*Board meeting schedules\s+(\d{4})\s*</caption>(.*?)</table>", t, re.S):
            for month, d1, d2 in re.findall(r'<th scope="row">(\w+)</th>\s*<td>(\d{1,2})&ndash;(\d{1,2}) \w+</td>', body):
                out.append(datetime.strptime(f"{d2} {month} {year}", "%d %B %Y").date())
        return sorted(out)
    ms = meetings()
    if ms:
        nxt = next((m for m in ms if m >= NOW.date()), None)
        extra["next_rba_decision"] = nxt.isoformat() if nxt else None
        if nxt and nums and any(x["key"] == "cash_rate" for x in nums):
            for x in nums:
                if x["key"] == "cash_rate":
                    x["note"] = (x["note"] + ". " if x["note"] else "") + f"Next decision {nxt.strftime('%A %d %B %Y')}"

    @source("RBA bond yields (table F2)", "https://www.rba.gov.au/statistics/tables/#interest-rates")
    def bonds():
        return {k: rba_series("f2", sid) for k, sid in (("au10y", "FCMYGBAG10D"), ("au3y", "FCMYGBAG3D"))}
    b = bonds()
    if b:
        for k, lbl in (("au3y", "Australian 3 year bond yield"), ("au10y", "Australian 10 year bond yield")):
            s = b[k]
            add(k, lbl, s[-1][1], s[-2][1] if len(s) > 1 else None, "%", s[-1][0], "Reserve Bank of Australia, table F2",
                "The RBA publishes these about two business days behind", 3, "Commodities and rates")

    abs_base = "https://data.api.abs.gov.au/rest/data"

    @source("ABS monthly CPI", "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation")
    def cpi():
        rows = list(csv.DictReader(io.StringIO(get(f"{abs_base}/ABS,CPI,2.0.0/3.10001+999902.10+20.50.M?lastNObservations=2&format=csv").text)))
        def pick(idx, ts):
            pts = sorted((r["TIME_PERIOD"], float(r["OBS_VALUE"])) for r in rows if r.get("INDEX") == idx and r.get("TSEST") == ts and r.get("OBS_VALUE"))
            if not pts:
                raise RuntimeError(f"CPI series {idx}/{ts} missing")
            return pts
        return {"headline": pick("10001", "10"), "trimmed": pick("999902", "20")}
    c = cpi()
    if c:
        for k, lbl in (("headline", "CPI inflation (annual, monthly CPI)"), ("trimmed", "Trimmed mean inflation (annual)")):
            pts = c[k]
            add("cpi_" + k, lbl, pts[-1][1], pts[-2][1] if len(pts) > 1 else None, "%", None, "Australian Bureau of Statistics",
                fmt_period(pts[-1][0]) + (" (seasonally adjusted)" if k == "trimmed" else ""), 1, "Australian economy")

    @source("ABS unemployment rate", "https://www.abs.gov.au/statistics/labour/employment-and-unemployment")
    def unemp():
        return abs_latest(f"{abs_base}/ABS,LF,1.0.0/M13.3.1599.20.AUS.M?lastNObservations=2&format=csv")
    u = unemp()
    if u:
        add("unemployment", "Unemployment rate", u[-1][1], u[-2][1] if len(u) > 1 else None, "%", None, "Australian Bureau of Statistics",
            fmt_period(u[-1][0]) + " (seasonally adjusted)", 1, "Australian economy")

    @source("ABS wage price index", "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/wage-price-index-australia")
    def wpi():
        return abs_latest(f"{abs_base}/ABS,WPI,1.2.0/3.THRPEB.7.TOT.20.AUS.Q?lastNObservations=2&format=csv")
    w = wpi()
    if w:
        add("wpi", "Wage price index (annual)", w[-1][1], w[-2][1] if len(w) > 1 else None, "%", None, "Australian Bureau of Statistics",
            fmt_period(w[-1][0]), 1, "Australian economy")

    @source("ABS release calendar", "https://www.abs.gov.au/release-calendar/future-releases")
    def calendar():
        t = get("https://www.abs.gov.au/release-calendar/future-releases").text
        out = []
        for when, name in re.findall(r'<time datetime="([^"]+)"[^>]*>.*?event-name">\s*([^<]+)</h3>', t, re.S):
            d = parse_date(when)
            if d:
                out.append({"date": d.astimezone(BNE).date().isoformat(), "name": clean(name, 120)})
        return out
    cal = calendar() or []
    keep = [x for x in cal if re.search(r"Consumer Price Index|Labour Force, Australia$|Wage Price Index|National Accounts|Retail|Monthly Household Spending", x["name"])]
    extra["abs_upcoming"] = keep[:8]
    return nums, extra


# ------------------------------------------------------------------ ASX announcements

ASX_API = "https://asx.api.markitdigital.com/asx-research/1.0"


def ann_row(it: dict, code: str, name: str = "") -> dict:
    when = parse_date(it.get("date"))
    return {"code": code.upper(), "name": name, "headline": clean(it.get("headline", ""), 200), "date": iso(when),
            "price_sensitive": bool(it.get("isPriceSensitive")), "type": (it.get("announcementType") or (it.get("announcementTypes") or [""])[0] or "").title(),
            "url": f"{ASX_API}/file/{it['documentKey']}" if it.get("documentKey") else ""}


def universe_codes() -> list[tuple[str, str, str]]:
    rows = list(csv.DictReader(open(ROOT / "config" / "universe.csv", encoding="utf-8")))
    out = []
    for r in rows:
        t = r.get("ticker", "")
        if r.get("status", "active") == "active" and t.endswith(".AX") and r.get("vehicle") != "cash":
            out.append((t[:-3], r.get("name", ""), r.get("vehicle", "")))
    return out


def announcements(days: int = 7) -> list[dict]:
    cutoff = NOW - timedelta(days=days)
    out, fails = [], 0
    for code, name, _ in universe_codes():
        try:
            d = get(f"{ASX_API}/companies/{code.lower()}/announcements", timeout=15, tries=2).json()
            for it in (d.get("data") or {}).get("items", []):
                row = ann_row(it, code, (d.get("data") or {}).get("displayName") or name)
                when = parse_date(row["date"])
                if when and when >= cutoff:
                    out.append(row)
        except Exception:  # noqa: BLE001
            fails += 1
        time.sleep(0.25)
    if fails and not out:
        raise RuntimeError(f"all {fails} company requests failed")
    SOURCES.append({"name": "ASX announcements (universe holdings)", "url": "https://www.asx.com.au/markets/trade-our-cash-market/announcements",
                    "ok": True, "items": len(out), "note": f"{fails} companies could not be fetched" if fails else ""})
    return sorted(out, key=lambda x: x["date"] or "", reverse=True)


@source("ASX price-sensitive announcements (whole market)", "https://www.asx.com.au/markets/trade-our-cash-market/announcements")
def market_price_sensitive(pages: int = 2) -> list[dict]:
    out = []
    for page in range(pages):
        d = get(f"{ASX_API}/markets/announcements?itemsPerPage=100&priceSensitiveOnly=true&page={page}").json()
        for it in (d.get("data") or {}).get("items", []):
            info = (it.get("companyInfo") or [{}])[0]
            out.append(ann_row(it, it.get("symbol", ""), info.get("displayName", "")))
    latest = max((parse_date(x["date"]) for x in out if x["date"]), default=None)
    if latest:  # the most recent trading day's announcements only
        day = latest.astimezone(BNE).date()
        out = [x for x in out if x["date"] and parse_date(x["date"]).astimezone(BNE).date() == day]
    return out


# ------------------------------------------------------------------ regulatory, legal and policy

# What makes an item "advice-related" for the page's filter: the subjects an adviser or paraplanner acts on.
ADVICE_TERMS = re.compile(r"financial advi|\badvisers?\b|\badvice\b|superannuation|\bsuper(annuation)? fund|\bsuper\b|SMSF|retirement|best interests|"
                          r"design and distribution|\bDDO\b|managed investment|investment platform|CSLR|compensation scheme|life insurance|"
                          r"\bscams?\b|greenwashing|Div(ision)? 296|trustee|MySuper|choice product|AFS licen|responsible entit|"
                          r"product disclosure|financial product|franking|pension|annuit|aged care|Centrelink|investors?\b|"
                          r"ASIC (Corporations|Superannuation|Credit)|Corporations (Amendment|Regulations)|Superannuation Industry|"
                          r"Shield|First Guardian|capital gains|negative gearing|deeming|transfer balance|contribution caps?", re.I)


def reg_item(src, title, link, when, summary="", tag="", relevant=None) -> dict:
    t = clean(title, 220)
    return {"source": src, "title": t, "link": link, "date": iso(when) if when else None, "summary": clean(summary, 240), "tag": tag,
            "relevant": bool(ADVICE_TERMS.search(t + " " + (summary or ""))) if relevant is None else relevant}


@source("ASIC media releases", "https://www.asic.gov.au/newsroom/")
def asic_media() -> list[dict]:
    d = get("https://download.asic.gov.au/asic-nga/data/newsroom/newsroom-mr-latest.json").json()
    items = d if isinstance(d, list) else d.get("items") or d.get("data") or []
    return [reg_item("ASIC", x.get("name", ""), "https://www.asic.gov.au" + x.get("url", "") if x.get("url", "").startswith("/") else x.get("url", ""),
                     parse_date(x.get("publishedDate")), x.get("metaDescription", ""), "Media release") for x in items]


@source("ASIC financial advice enforcement and bannings", "https://www.asic.gov.au/newsroom/")
def asic_advice(days: int = 45) -> list[dict]:
    d = get("https://download.asic.gov.au/asic-nga/data/newsroom/newsroom-bannings-alerts.json", timeout=60).json()
    items = d if isinstance(d, list) else d.get("items") or d.get("data") or []
    out = []
    for x in items:
        subj = " ".join(x.get("metaSubject") or []) if isinstance(x.get("metaSubject"), list) else str(x.get("metaSubject") or "")
        when = parse_date(x.get("publishedDate"))
        if when and when >= NOW - timedelta(days=days) and re.search(r"financial advice|bannings", subj, re.I):
            out.append(reg_item("ASIC", x.get("name", ""), "https://www.asic.gov.au" + x.get("url", "") if x.get("url", "").startswith("/") else x.get("url", ""),
                                when, x.get("metaDescription", ""), "Enforcement", relevant=True))
    return out


@source("APRA media releases", "https://www.apra.gov.au/news-and-publications")
def apra() -> list[dict]:
    t = get("https://www.apra.gov.au/news-and-publications?document_type%5B0%5D=tid%3A2002&created=2").text
    out = []
    for block in t.split('class="views-row"')[1:]:
        m = re.search(r'<h2>\s*<a href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        d = re.search(r"Published\s*</div>\s*<div[^>]*>\s*([^<]+?)\s*</div>", block, re.S)
        if m:
            out.append(reg_item("APRA", m.group(2), "https://www.apra.gov.au" + m.group(1) if m.group(1).startswith("/") else m.group(1),
                                parse_date(d.group(1)) if d else None, "", "Media release"))
    return out


def rss_source(name: str, url: str, src: str, tag: str, *, relevant=None, keep=None, limit: int = 30):
    @source(name, url)
    def run():
        items = rss_items(get(url).content)
        out = []
        for it in items:
            title, desc = it.get("title", ""), it.get("description") or it.get("summary") or ""
            if keep and not keep(title, desc):
                continue
            out.append(reg_item(src, title, it.get("link", ""), it.get("when"), desc, tag, relevant))
        return out[:limit]
    return run()


@source("Treasury consultations", "https://treasury.gov.au/consultation")
def treasury_consultations() -> list[dict]:
    t = get("https://treasury.gov.au/consultation").text
    out = []
    for block in t.split('class="views-row"')[1:]:
        st = re.search(r"field__item\s+(open|closed)", block)
        m = re.search(r'<a href="(/consultation/[^"]+)"[^>]*>(.*?)</a>', block, re.S)
        times = re.findall(r'<time datetime="([^"]+)"', block)
        if m and st and st.group(1) == "open":
            opened = parse_date(times[0]) if times else None
            closes = parse_date(times[1]) if len(times) > 1 else None
            out.append(reg_item("Treasury", m.group(2), "https://treasury.gov.au" + m.group(1), opened,
                                f"Open for comment{(' until ' + closes.astimezone(BNE).strftime('%d %B %Y')) if closes else ''}", "Consultation"))
    return out


@source("Federal Register of Legislation", "https://www.legislation.gov.au/")
def legislation(days: int = 30) -> list[dict]:
    since = (NOW - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00")
    out, seen = [], set()
    for word in ("Corporations", "Superannuation", "ASIC", "Taxation", "Financial Sector", "Treasury Laws"):
        q = (f"https://api.prod.legislation.gov.au/v1/Titles?$filter=asMadeRegisteredAt ge {since} and contains(name,'{word}')"
             f"&$orderby=asMadeRegisteredAt desc&$top=40&$select=id,name,collection,asMadeRegisteredAt")
        try:
            d = get(q.replace(" ", "%20").replace("'", "%27"), timeout=30).json()
        except Exception:  # noqa: BLE001
            continue
        for x in d.get("value", []):
            if x["id"] in seen:
                continue
            seen.add(x["id"])
            out.append(reg_item("Legislation", x.get("name", ""), f"https://www.legislation.gov.au/{x['id']}/asmade", parse_date(x.get("asMadeRegisteredAt")),
                                (x.get("collection") or "").replace("LegislativeInstrument", "Legislative instrument"), "New law or instrument"))
        time.sleep(1)
    if not out and not seen:
        raise RuntimeError("no results (API may be unavailable)")
    return sorted(out, key=lambda x: x["date"] or "", reverse=True)


def regulatory() -> list[dict]:
    allx: list[dict] = []
    for fn in (asic_media, asic_advice, apra, treasury_consultations, legislation):
        allx += fn() or []
    feeds = [
        ("Treasurer media releases", "https://ministers.treasury.gov.au/ministers/jim-chalmers-2022/media-releases/feed", "Treasurer", "Minister"),
        ("Financial Services minister media releases", "https://ministers.treasury.gov.au/ministers/daniel-mulino-2025/media-releases/feed", "Financial Services minister", "Minister"),
        ("RBA media releases", "https://www.rba.gov.au/rss/rss-cb-media-releases.xml", "RBA", "Media release"),
        ("FAAA media releases", "https://faaa.au/category/media-releases/feed/", "FAAA", "Industry"),
    ]
    for name, url, src, tag in feeds:
        allx += rss_source(name, url, src, tag) or []
    allx += rss_source("Federal Court judgments (ASIC, tax, super, advice)", "https://www.judgments.fedcourt.gov.au/rss/fca-judgments", "Federal Court", "Judgment",
                       relevant=True, keep=lambda t, d: bool(re.search(r"\bASIC\b|Australian Securities and Investments Commission|Commissioner of Taxation|superannuation|"
                                                                      r"financial advi|financial services licen|managed investment scheme", t + " " + d)), limit=25) or []
    gn = "https://news.google.com/rss/search?q={q}+when:14d&hl=en-AU&gl=AU&ceid=AU:en"
    allx += rss_source("ATO news (via Google News)", gn.format(q="site:ato.gov.au"), "ATO", "Tax", limit=12) or []
    allx += rss_source("AFCA news and determinations (via Google News)", gn.format(q="site:afca.org.au"), "AFCA", "Complaints", relevant=True, limit=12) or []
    cutoff = NOW - timedelta(days=30)
    allx = [x for x in allx if not x["date"] or parse_date(x["date"]) >= cutoff]
    seen, out = set(), []
    for x in sorted(allx, key=lambda x: x["date"] or "", reverse=True):
        k = (x["title"].lower(), x["source"])
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


# ------------------------------------------------------------------ market wrap headlines

def wrap() -> list[dict]:
    keep = lambda t, d: bool(re.search(r"\bASX\b|sharemarket|share market|S&P/ASX|Australian shares", t, re.I))
    out = []
    out += rss_source("Yahoo Finance Australia top stories", "https://au.finance.yahoo.com/rss/topstories", "Yahoo Finance", "Market", keep=keep, limit=8) or []
    out += rss_source("ABC News business", "https://www.abc.net.au/news/feed/51892/rss.xml", "ABC News", "Market", keep=keep, limit=6) or []
    cutoff = NOW - timedelta(days=3)
    out = [dict(x, summary="") for x in out if not x["date"] or parse_date(x["date"]) >= cutoff]   # headlines and links only
    return sorted(out, key=lambda x: x["date"] or "", reverse=True)[:12]


# ------------------------------------------------------------------ the universe's biggest moves

def movers(n: int = 8) -> dict:
    p = ROOT / "data" / "cache" / "prices.csv"
    if not p.exists():
        SOURCES.append({"name": "Universe price moves (build price cache)", "url": "", "ok": False, "items": 0, "note": "no price cache on this run"})
        return {}
    import pandas as pd
    px = pd.read_csv(p, index_col=0, parse_dates=True).sort_index()
    uni = pd.read_csv(ROOT / "config" / "universe.csv")
    act = uni[(uni["status"] == "active") & (uni["vehicle"] != "cash")]
    names = dict(zip(act["ticker"], act["name"]))
    cols = [c for c in act["ticker"] if c in px.columns]
    last = px[cols].ffill().iloc[-2:]
    if len(last) < 2:
        return {}
    ch = (last.iloc[-1] / last.iloc[-2] - 1).dropna() * 100
    ch = ch[ch.abs() < 60]
    rows = lambda s: [{"ticker": t, "name": names.get(t, t), "change_pct": round(float(v), 2), "price": round(float(last.iloc[-1][t]), 3)} for t, v in s.items()]
    out = {"as_of": str(px.index[-1].date()), "up": rows(ch.sort_values(ascending=False).head(n)), "down": rows(ch.sort_values().head(n)),
           "breadth": {"up": int((ch > 0).sum()), "down": int((ch < 0).sum()), "flat": int((ch == 0).sum())}}
    SOURCES.append({"name": "Universe price moves (build price cache)", "url": "", "ok": True, "items": len(ch), "note": ""})
    return out


# ------------------------------------------------------------------ main

def build() -> dict:
    print("Daily brief: key numbers")
    nums, extra = key_numbers()
    print("Daily brief: announcements")
    try:
        anns = announcements()
    except Exception as e:  # noqa: BLE001
        SOURCES.append({"name": "ASX announcements (universe holdings)", "url": "", "ok": False, "items": 0, "note": str(e)[:160]})
        anns = []
    mkt = market_price_sensitive() or []
    print("Daily brief: regulatory and legal")
    reg = regulatory()
    print("Daily brief: market wrap and movers")
    wr = wrap()
    mv = movers()
    held = {c for c, _, _ in universe_codes()}
    for a in mkt:
        a["held"] = a["code"] in held
    return {"generated_at": NOW.isoformat(timespec="minutes"), "date": NOW.date().isoformat(), "numbers": nums, "extra": extra,
            "announcements": anns, "market_price_sensitive": mkt, "regulatory": reg, "wrap": wr, "movers": mv, "sources": SOURCES}


def main(argv: list[str]) -> int:
    out = ROOT / "output"
    out.mkdir(exist_ok=True)
    path = out / "brief.json"
    if "--no-fetch" in argv and path.exists():
        data = json.loads(path.read_text())
    else:
        data = build()
        path.write_text(json.dumps(data, indent=1, default=str))
    # The build's data check (portfolio_engine/freshness.py), shown at the top of the brief.
    fp = out / "freshness.json"
    try:
        data["freshness"] = json.loads(fp.read_text()) if fp.exists() else None
    except (OSError, ValueError):
        data["freshness"] = None
    from portfolio_engine.reports.brief import write_brief
    page = write_brief(out / "brief.html", data)
    ok = sum(1 for s in data["sources"] if s["ok"])
    print(f"Daily brief: {ok} of {len(data['sources'])} sources ok; {len(data['announcements'])} announcements, {len(data['regulatory'])} regulatory items -> {page}")
    for s in data["sources"]:
        if not s["ok"]:
            print(f"  unavailable: {s['name']}: {s['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
