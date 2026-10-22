# 📈 Screener IDX30 (v4.2)

A technical-analysis screener for Indonesian stocks (IDX / BEI), built with Streamlit. It downloads daily price data from Yahoo Finance, scores each stock on trend, momentum, volume and price location, builds a stop-loss / target / position-size plan, and produces a ranked report with charts.

> **Disclaimer:** this is a screening tool, not a buy/sell recommendation. The 20-day price range is a risk simulation without drift, not a forecast. Always do your own research.

---

## Features

- **Batch data download** – one `yf.download` call for the whole universe, with a 30-minute in-memory cache.
- **Market structure** – swing pivots, trendlines, support/resistance, Fibonacci golden zone, HH/HL vs LH/LL structure, BOS/CHoCH.
- **Indicators** – MA20/50/200, RSI, ATR, ADX (+DI/−DI), Bollinger Bands, VWMA, anchored VWAP, weekly trend, relative strength vs IHSG.
- **Volume analysis** – RVOL, breakout validity, "volume rawan palsu" (unreliable volume) warning.
- **Price action** – candlestick patterns and hidden divergence.
- **Scoring** – four capped groups (see below), then a category and an A/B/C quality grade.
- **Risk plan** – ATR/support-based stop loss, TP1/TP2, R/R, lot sizing from account risk, and worst-case loss if the stock hits ARB (auto-rejection bottom).
- **Risk projection** – Filtered Historical Simulation (FHS) of 1,500 price paths; shows P10 / P50 / P90 and the probability of touching support or resistance within the horizon.
- **Diversified Top-N** – limits stocks per sector and rejects highly correlated picks.
- **Optional corporate events** – ex-dividend / earnings date check (slower, off by default).
- **Two views** – full-universe screener and a single-stock detail page.

## How scoring works

The score is the sum of four groups, each capped so that overlapping signals are not counted twice:

| Group | Range |
|---|---|
| Trend | ±5 |
| Momentum | ±4 |
| Volume | ±2 |
| Location / setup | ±3 |
| **Total** | **±14** |

Categories: **Kandidat kuat** (score ≥ 9 with bullish bias), **Pantau, bias naik** (≥ 6), **Potensi memantul** (weak bias but confirmation near support), **Pantau**, **Netral**, **Hindari dulu**, **Illiquid**. A bullish candidate whose R/R is below the configured minimum is downgraded to *Pantau*.

The **A/B/C grade** counts how many of 10 quality checks pass (trend, structure, volume, RSI zone, location, ADX, relative strength, R/R, MA200, liquidity).

## Quick start

Requires Python 3.10+.

```bash
git clone <your-repo-url>
cd technical-analysis
pip install -r requirements.txt
streamlit run app.py
```

The app opens at `http://localhost:8501`.

### Deploy on Streamlit Community Cloud

1. Push the repo to GitHub.
2. Create a new app on [share.streamlit.io](https://share.streamlit.io) pointing to `app.py`.
3. Dependencies are installed automatically from `requirements.txt`.

A GitHub Codespaces / dev container config is included in `.devcontainer/`.

## Usage

**Sidebar settings**

| Setting | Default | Description |
|---|---|---|
| Periode | `2y` | History to download (`1y`, `2y`, `5y`). Minimum ~120 bars per stock. |
| Horizon proyeksi | 20 days | Horizon of the FHS simulation. |
| Universe | IDX30 list | One ticker per line; `.JK` is appended automatically. |
| Min R/R | 1.5 | Minimum reward/risk for a buy candidate. |
| Min likuiditas | Rp 10 miliar | Minimum daily traded value. |
| Top N | 5 | Number of diversified top picks. |
| Cek event | off | Ex-dividend / earnings check (1 extra request per stock). |
| Grafik Top | on | Include charts on the top-pick cards. |

Click **🚀 Jalankan Scan** to run. Use **🔄 Refresh data** to clear the cache and results.

Account and risk parameters (capital, risk per trade, max position size, ARB %, sector and correlation limits) live at the top of `screener_core.py`:

```python
MODAL = 100_000_000      # account size (Rp)
RISIKO_PCT = 1.0         # % of capital risked per trade
MAKS_POSISI_PCT = 25.0   # max position size, % of capital
ARB_PCT = 0.15           # auto-rejection bottom
MAKS_PER_SEKTOR = 2
MAKS_KORELASI = 0.80
```

Sector and name maps (`SEKTOR`, `NAMA`) cover the default universe; tickers outside it appear under sector "Lainnya".

## Project structure

```
.
├── app.py              # Streamlit UI (sidebar, scan tab, single-stock tab)
├── screener_core.py    # All analysis: data, indicators, scoring, risk, FHS, charts, HTML report
├── requirements.txt    # streamlit, yfinance, mplfinance, pandas, numpy, matplotlib
└── .devcontainer/      # Codespaces / dev container config
```

`screener_core.py` can also be used without Streamlit:

```python
import screener_core as sc

tickers = sc.IDX30_DEFAULT
ihsg = sc.ambil_ihsg("2y")
hasil, gagal = sc.scan_universe(tickers, ihsg)   # gagal = [(ticker, reason), ...]
df = sc.buat_tabel(hasil)
top, dilewati = sc.pilih_top(df, hasil, n=5)
```

## Notes and troubleshooting

- **Data source:** Yahoo Finance via `yfinance`, with `auto_adjust=False` so price levels match broker charts. IDX data on Yahoo can have gaps or bad ticks, and ex-dividend / earnings data is often empty.
- **Unfinished bar:** while the market is open (before 16:15 WIB on weekdays) today's bar is dropped, so all signals use completed daily candles.
- **Stocks listed under "Gagal":** the scan continues if one stock fails. A stock appears there when data is empty, too short, or its price history is abnormal (e.g. zero prices, long-stale prices followed by a jump) and the FHS projection cannot be computed reliably.
- **Streamlit Cloud rate limits:** Yahoo may throttle shared cloud IPs. If many tickers fail, wait a few minutes and use **Refresh data**.

## Author

Muhammad Ribhan Hadiyan — [ribhanhadyan.vercel.app](https://ribhanhadyan.vercel.app/)
