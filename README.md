# Portfolio Engine

A Python program that generates model portfolios for every combination of risk profile,
life stage and balance tier from your HUB24 investment universe, prices them from live
market data, applies bounded rule-based tactical tilts, and writes an Excel workbook and
an HTML dashboard. It can also compare a real account to its target and produce a trade
list.

This is a learning and portfolio project. It is not financial advice and it is not a
licensee-approved investment process. Every rule is in a config file so you can defend or
change it.

## What it produces

Running `build` creates, in `output/`:

* `model_portfolios_<date>.xlsx` and `model_portfolios_latest.xlsx`: a Summary matrix of
  every portfolio, Allocation tables (strategic weights, current tilts, final weights),
  Signals, all Holdings in one filterable table, one sheet per distinct portfolio, the
  Universe with latest prices, and the Assumptions used.
* `dashboard.html`: a self-contained page with a guided selector, plain-English readouts, a
  clickable fact sheet for every holding (description, returns, analyst view, 52 week range)
  and a Print button that lays the holdings page out for A4.
* `builder.html`: the "Build your own portfolio" page (see below).
* `portfolios_<date>.json`: everything, for any other tool you want to feed.

## How a portfolio is built

1. **Risk profile** gives the strategic asset allocation (SAA) across seven classes:
   Australian equities, international equities, property and infrastructure, alternatives,
   fixed income, credit and hybrids, cash. The Balanced SAA is anchored on your HUB24
   true balanced 70/30 model; the other four profiles scale around it.
2. **Tactical tilts** move each class by at most 5 percentage points from its SAA, and the
   net growth-versus-defensive shift is also capped at 5 points. The signals are trend
   (price versus 200 day average), momentum (12-1 month return less cash) and a
   volatility-spike penalty, computed on a proxy ETF per class. Hysteresis of 1 point
   stops the tilt flickering. The Signals sheet shows every input, so any tilt can be
   traced back to the numbers that produced it.
3. **Life stage** (Early accumulator, Accumulator, Retirement) caps the profile (retirement cannot exceed Balanced), sets a cash floor, adds a home bias toward Australian equities in
   the drawdown stages, and scores holdings for income and franking.
4. **Balance tier** decides implementation: which vehicle types are allowed, how many
   holdings, minimum holding size, brokerage. Under $50,000 the engine uses one low cost
   ETF per class (the "fallback" holdings), because 31 holdings at $800 each is brokerage
   drag, not diversification.
5. Holdings are weighted from your model's allocation hints, capped per holding, converted
   to whole units at the latest AUD price (USD holdings converted at AUDUSD), and the
   rounding residual goes to the cash account.
6. Metrics include weighted MER, yield and income, the HUB24 administration fee from the
   rate card for the menu the account would sit on (Choice for anything holding listed
   securities; Core for managed-portfolio-only accounts, or Discover under $100,000),
   total ongoing cost, **realised volatility from the covariance of the holdings' returns**,
   beta and correlation to the ASX 200 (VAS) and world shares (VGS), the average
   correlation between holdings, a diversification ratio, each holding's beta, and a
   correlation grid between the asset class index ETFs. Your spreadsheet's "Vol" column is a weighted average of individual
   volatilities; that ignores diversification and overstates portfolio risk, so both numbers
   are shown side by side.

## Setup

```bash
cd portfolio-engine
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Load your HUB24 model

```bash
python scripts/import_hub24.py "path/to/HUB24 Portfolios.xlsx"
```

This reads the holdings table (section headers, Code, Type, Alloc %, MER %, Yield %) into
`config/universe.csv` and adds any unpriceable holdings (term deposit, notes, unlisted
funds, cash account) to `data/manual_prices.csv`. Then edit:

* `config/universe.csv`: `franking` is set to 0 for every holding because the model does
  not record it; fill it in for the retirement income scoring to mean anything. Review
  `min_tier` (which balance tier a holding first becomes eligible for), `max_weight`,
  `priority` (lower is chosen first within a class) and `weight_hint`.
* `data/manual_prices.csv`: only the cash account, at 1.00. Unlisted funds, term deposits
  and notes were removed from the universe because they have no automated price; add them
  back here only if you are prepared to update their prices by hand.
* `config/profiles.yaml`: SAA, life stage rules, tier rules, tactical parameters.
* `config/settings.yaml`: data sources, cache age, rebalance tolerances, platform fee card.

### Run

```bash
python -m portfolio_engine build                 # everything, with live prices
python -m portfolio_engine build --no-tactical   # strategic weights only
python -m portfolio_engine single --profile balanced --stage retirement --balance 350000
python -m portfolio_engine rebalance --holdings data/sample_holdings.csv --profile balanced --stage accumulation
python -m portfolio_engine signals               # print the tactical inputs
python -m portfolio_engine refresh               # refresh the price cache only
python -m portfolio_engine --offline build       # synthetic prices, for testing the pipeline
```

Profiles: `conservative`, `moderate`, `balanced`, `growth`, `high_growth`.
Stages: `early_accumulation` (Early accumulator), `accumulation` (Accumulator), `retirement`.

A holdings file for `rebalance` needs a `ticker` column and either `units` or `value`.

### Managed portfolio (SMA) route for smaller balances

For the starter and core tiers the build also produces a managed portfolio variant: one
diversified managed portfolio from the HUB24 menu (`config/sma_menu.csv`, extracted from the
fee calculator with `python scripts/import_sma_menu.py <calculator.xlsx>`) that matches the
risk profile, plus the life stage cash floor. Candidates come from the matching
"Multi Sector" category with at least three years of history, ranked by total fee; the
shortlist is shown and the cheapest is used. Managed portfolios have no market price feed:
fees and reported returns are the platform's published figures as of the menu date, and
risk figures use the profile's ETF proxies. Under $100,000 the account sits on the Discover
menu (`config/discover_menu.csv`, from the Discover investment booklet): no administration or
account keeping fee, the shortlist is limited to portfolios on that menu, and the booklet's
underlying fees and transaction costs replace the calculator's; the manager fee stays the
Core menu figure because the booklet discloses it only as "tiered". `python -m portfolio_engine single --sma ...`
builds one directly. Tune the rules in the `sma` section of `profiles.yaml`.

### Pension rules

The drawdown stages score holdings on grossed-up yield (cash dividend plus the franking
credit a zero-tax pension account gets refunded), skip equity holdings under a minimum
grossed-up yield, rank income LICs and high-yield ETFs ahead of growth satellites, and move
part of the international sleeve to Australian shares. Outputs report cash yield,
franking credits per year and the grossed-up yield. Tune `income_preference`,
`franking_preference`, `home_bias_pp` and `min_equity_yield_pct` per life stage in
`profiles.yaml`.

### Exact balances and Excel on the website

The website's "Your balance" box recalculates the selected portfolio for an exact balance:
tier chosen by balance, whole units, platform fee from the rate card, income and franking
credits in dollars. "Download this portfolio as Excel" writes a workbook for that balance
with a sheet per tier; the full workbook with every portfolio is linked alongside.

### Adding and removing holdings yourself

```bash
python -m portfolio_engine add BHP.AX --class aus_equity            # checks the ticker prices, then adds it
python -m portfolio_engine add NDQ.AX --class intl_equity --vehicle etf --role satellite --tier core --hint 3
python -m portfolio_engine remove ELD.AX                              # moves it to the watchlist
```

Manual additions live in `data/my_holdings.csv` (one line per ticker; name, price, yield and
research are fetched on the next build). `config/universe.csv` has a `status` column:
`active` holdings are eligible for portfolios, `watchlist` names are screened by the review
but not held.

### Holding review (proposed adds and removes)

`python -m portfolio_engine review` screens every active holding for strikes (below its 200
day average, momentum well behind its asset class index, a fall of more than a third from its
one-year high, an Underperform or Sell consensus, market cap below the floor) and every
watchlist name for merits (the reverse, plus volatility no worse than its peers). Three
strikes propose a removal; three merits and no strikes propose an addition. Proposals go to
the dashboard, the workbook's Review sheet and `review --apply` makes up to
`review.max_changes_per_run` of them with a `review.cooling_off_days` window. Set
`review.auto_apply: true` in `settings.yaml` if you want the daily build to apply them
unattended; I recommend leaving it false.

### Returns and yields

Per holding: 1 year total return and 3, 5 and 10 year annualised total returns from
dividend-adjusted prices. A holding younger than the period uses its asset class index ETF
(`returns.long_history_proxies`) and is marked as a proxy. Per portfolio: the weighted average
of holding returns for 3, 5 and 10 years, with the share of the portfolio relying on proxies,
plus the weighted yield. Yields come from the price feed's trailing 12 month dividends where
available (marked `live`), otherwise the configured figure.

### Holding research and analyst consensus

`python -m portfolio_engine research` prints, for every listed holding, the Yahoo Finance
analyst consensus (mean rating 1 to 5 across covering brokers, number of analysts, mean price
target), 1, 3 and 5 year total returns from dividend-adjusted prices, volatility, worst
drawdown, dividend yield and sector. Fundamentals are cached for a week
(`research.max_age_days`); pass `--refresh-research` to refetch now. The consensus scales a
holding's weight within its class by at most `research.consensus_weighting` (default 25%)
and flags names at or above `research.review_threshold` for review. It never sells anything.

### Market data

Prices come from Yahoo Finance via `yfinance` (ASX tickers use the `.AX` suffix, US
tickers are bare), with Stooq as a fallback and per-ticker CSVs in `data/prices/` as a
last resort. Prices are cached in `data/cache/prices.csv` for 20 hours. Yahoo is an
unofficial source: it is fine for a learning tool and not something a licensee would run
client reporting on.

### Automatic updates (GitHub Actions)

The daily build runs in the cloud, in `.github/workflows/daily-build.yml`: every weekday at 18:40 Brisbane
time a GitHub-hosted runner installs the project, pulls any holding changes queued on the website, refreshes
prices and research, rebuilds every portfolio, publishes the site to Netlify and commits the engine's own
records (`config/universe.csv`, `data/my_holdings.csv`, the tactical state) back to the repository. A second,
three-hourly schedule rebuilds only when the website has queued changes. "Run workflow" on the Actions tab
forces a build at any time.

Publishing needs no secrets. The workflow force-pushes the finished site (pages, functions and their config) to
the `site` branch, with history discarded each day so the repository stays small, and Netlify, linked to the
repository with `site` as its production branch and `site` as the publish directory, deploys it from there.
Holding changes queued on the website are cleared the same way: the build publishes the ids it has applied in
`site/data/applied_changes.json` and the `changes` function reads that file.

Nothing runs on your Mac any more. If the old launchd jobs are still installed, double-click
`Stop Mac schedule.command` once to remove them; otherwise they would publish stale pages over the cloud build.
(They had in any case stopped working on 4 September 2026: macOS refuses to let a background job read the
Documents folder, so every run failed with "Operation not permitted".)

To run a build by hand on any machine: `python -m portfolio_engine --refresh build`, then `bash scripts/run_build.sh`
publishes if `.netlify/auth_token` and `.netlify/state.json` exist.

### The portfolio builder and accounts

`output/builder.html` (published as `/builder.html`) lets a visitor assemble a portfolio from any listed
holding. The engine's universe is offered first, with research, verdicts and ten years of history; anything
else is fetched live through the site's `/history` function (price, dividends, ten years of monthly returns
converted to Australian dollars, a year of daily returns), so fees, income, risk, diversification and the
backtest work for any share or ETF on the ASX, in the United States, Canada, Europe or New Zealand.
Unlisted managed funds and term deposits are not in the price feed and cannot be added.

Accounts use Supabase: the project URL and the publishable key live in `config/settings.yaml` under
`accounts.supabase` (they are meant to be public), and `supabase/schema.sql` creates the `portfolios` table
with row level security so a signed-in visitor can read, change and delete only their own rows, plus any
row its owner has marked shared. Run the SQL once in the Supabase SQL editor, and set the project's
Authentication, URL Configuration, Site URL to the published site so confirmation emails link back to it.
Without accounts configured the page still works; drafts stay in the browser.

### Platforms, undo and basis of advice in the builder

`config/platforms.yaml` holds each platform's published fee schedule (HUB24, Netwealth, BT Panorama, Praemium,
Macquarie Wrap and CFS Edge super accounts, plus Morgans Wealth+, whose fee is not published and is entered on the
page). Each menu has its tiered administration fee, minimum and cap, fixed fees, percentage levies with caps, any fee on
international listed securities, whether it can hold listed securities, and brokerage. The builder's Platform picker
uses it, "Cheapest menu that fits" picks the lowest-cost menu that can hold the portfolio, and a table compares every
platform at the current balance. Each schedule carries its document date and link; Macquarie Wrap and CFS Edge are
marked "to confirm" because their figures were read through a summary rather than line by line. Update the file when a
PDS changes.

Undo and redo (buttons, or Ctrl or Cmd + Z and Ctrl or Cmd + Shift + Z) step through every change on the builder page.
Each holding gets an automatic basis of advice draft from its own figures, which keeps up with the weights until it is
edited; edited text is kept. Both are saved with the portfolio and written to the Excel download (a "Basis of advice"
sheet and a column on the Holdings sheet). Save works without an account (the portfolio is kept in the browser) and
falls back to the browser if the account cannot be reached.

The base portfolios use three stages of life: Early accumulator, Accumulator and Retirement.

### Compare page

`/compare.html` has two tabs. Platforms: the cost of every platform and menu in `config/platforms.yaml` at any balance,
number of listed holdings, international share and trading activity, a chart of cost against balance, and each menu's
features. Super funds: every MySuper product and choice investment option from APRA's Comprehensive Product
Performance Package (`python scripts/super_funds.py`, refreshed weekly by the build into `data/super_funds.json` and
published as `/data/super.json`): fees at five balances, 3, 5, 7 and 10 year returns, the performance test result, growth
allocation, size and members, with filters, side-by-side comparison of up to five and Excel download. APRA does not
publish insurance, member services or other benefits, so they are not shown.

### Importing models, the portfolio check and the AI review

The builder imports a model from any Excel or CSV sheet with a column of codes (ASX codes, tickers or HUB24 codes) and
a column of weights, dollar values or units; section headings set the asset class and unmatched codes are listed. The
portfolio check applies fixed rules (allocation against the target, concentration, analyst and quality warnings, cost,
platform savings, overlap, cash, volatility, correlation, income, small holdings, unfinished basis of advice) with a
reason for each and buttons that make the change. The AI review sends the portfolio's figures and the check's findings to
Claude through the `review-background` function (signed-in accounts only, 25 reviews per account a day, results read
back through `review-status`); it needs the `ANTHROPIC_API_KEY` environment variable on the Netlify site.

### Daily brief

`python scripts/daily_brief.py` fetches the key market and economic numbers (Yahoo Finance, the RBA's statistical
tables and meeting schedule, the ABS Data API and release calendar), the last week's ASX announcements for every active
ASX holding in the universe, the market's price-sensitive announcements, regulatory, legal and policy updates (ASIC,
APRA, Treasury ministers and consultations, the Federal Register of Legislation, Federal Court judgments, the RBA, the
FAAA, and ATO and AFCA news through Google News because both refuse automated requests) and market wrap headlines,
and writes `output/brief.json` and `output/brief.html` (published as `/brief.html`). Every source fails on its own and
is listed on the page with its status. The page filters each list and downloads the whole brief as Excel; the
`/asx` function looks up any ASX code live.

### Missed evenings

GitHub does not guarantee scheduled runs; on 5 October 2026 the 18:40 run never started. Every three-hourly run now
checks `/data/build.json` on the published site and rebuilds if it is older than the most recent weekday 18:30 in
Brisbane, so a skipped evening is caught up within about three hours.

### Diversification rules

`diversification` in `config/profiles.yaml` governs how holdings are chosen and weighted within an asset
class. Candidates are ordered so the first name from each sector comes before any sector gets a second
(for funds, each sector and region), single companies are limited per sector by tier, international
single companies are limited to a share from any one country, no sector of single companies may exceed a
share of its class, and no single company may exceed a share of the whole portfolio. Every holding in
`config/universe.csv` carries `sector` and `region`; blanks are filled from the research feed and the
listing. The dashboard and the builder show weight by sector and region, the effective number of holdings
and flags against these rules.

### Currencies

`market_data.fx_tickers` in `config/settings.yaml` lists the FX pairs for each trading currency in the
universe (USD, EUR, CAD, GBP, NZD). Prices and the monthly history are converted to Australian dollars;
daily returns used for beta and correlation stay in each holding's own currency.

### Tests

```bash
python -m pytest tests -q
```

The tests run on synthetic prices and check that every portfolio in the matrix sums to
100 percent and to the balance, respects the tier's holding limits and minimum sizes, the
life stage cap and cash floor, that tilts are zero-sum and bounded, and that the
retirement variant yields more than the accumulation variant.

## Known limitations and where to take it next

* Tactical tilts are a rule, not a forecast. Trend and momentum rules are well documented
  in the literature but they whipsaw in sideways markets and the transaction costs of
  acting on them at small balances can exceed the benefit. The `rebalance` tolerance bands
  exist so you do not trade on every wobble.
* Within a class, holdings are chosen by `priority` then `weight_hint`. The importer gives
  funds and LICs priority 2 and direct shares priority 3, so at the Core tier (under
  $250,000) the Australian sleeve is built from ARG, FGX and VSO rather than direct shares.
  If you want direct shares earlier, change `priority` or `max_per_class`.
* Expected returns are deliberately absent. Trailing return is shown as history only.
  The 3, 5 and 10 year figures in the source spreadsheet are not carried across because
  a 67 percent three-year return on Sigma is not an expectation for the next three.
* The Choice and Core administration bands are the September 2024 Super card from the HUB24
  adviser fee calculator; the current PDS Part II could not be read by machine, so verify
  them against your statement. The Discover menu (no administration fee) is from
  hub24.com.au/discover. Update the `platform.menus` section of `config/settings.yaml`
  when they change.
* ESG screen: the website's "ESG screen" toggle switches every portfolio to a screened twin built
  from `config/esg.yaml` (exclusions, ETF substitutions, managed portfolio name filter) and the
  written verdicts in `config/esg_review.csv`. There is no ratings feed behind it (Yahoo stopped
  serving Sustainalytics scores), so every band is a dated written opinion; add a provider rating
  to the CSV when you have access to one. `python -m portfolio_engine single ... --esg` builds one.
* Every holding carries a product documents link (`config/pds_links.csv` overrides; otherwise
  the ASX company page, the Cboe product page, SEC filings for US names, or the HUB24 super
  documents page for managed portfolios).
* Franking credits are not modelled beyond a scoring preference until `franking` is
  populated in the universe.

### The research screen

`python scripts/universe_scorecard.py` scores every listing the site knows about (about 1,100: ASX companies over
$300 million, the S&P 500 and the Australian ETF list, plus everything already in the universe) on size, 1, 3, 5
and 10 year returns, volatility, worst fall, recent momentum and analyst consensus, 0 to 100, and writes the whole
table to `config/universe_scorecard.csv` (also published at `/data/universe_scorecard.csv`). With `--apply` it adds
the best-scoring large listings that are not yet in the universe (at most 80 a run, $8 billion or more, three years
of history) and moves an active share to the watchlist when it is down over three and five years and below its
200 day average, or carries a Sell consensus with a falling price. Amcor is never added. The daily workflow runs
the screen every day and applies it on Mondays.

### Profile fit

Each holding gets a fit score per risk profile (`selection` in `config/profiles.yaml`): trend, momentum, 3, 5 and
10 year returns, low volatility, consensus, grossed-up yield and its style (growth, quality, income, defensive),
weighted differently for High Growth than for Conservative. Index cores stay in front; everything else is ranked
on fit, and the sector spread is applied only within the best-fitting pool. A company that is down over three
and five years is not eligible for the Growth and High Growth profiles; one above the volatility limit is not
eligible for Conservative and Moderate; a Sell consensus excludes a share everywhere. The notes on each portfolio
say what was left out and why.

### Unlisted funds

`config/unlisted_funds.csv` holds managed funds without a daily price feed: the manager's unit price and
published returns (dated), a listed twin whose daily and monthly history stands in for risk and the backtest,
the liquidity terms and the PDS link. They appear in the universe as `fund` holdings priced "manual", are
limited to the larger balance tiers, and the page and workbook say which twin is standing in.
