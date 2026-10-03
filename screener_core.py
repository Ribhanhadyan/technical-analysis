# screener_core.py — Screener IDX30 v4.2 (pure analisa teknikal, tanpa backtest)
# Perubahan v4.2 vs v4.1 (perhitungan skor TIDAK berubah):
#   - Backtest dihapus total (config, fungsi, HTML)
#   - Data diunduh BATCH (satu yf.download untuk seluruh universe) + cache TTL 30 menit
#   - time.sleep antar saham dihapus; cek event (exdiv/laporan) opsional, default OFF
#   - Simulasi FHS 3000 -> 1500 jalur (percentil tetap stabil)
#   - Bagian tampilan (HTML) yang sebelumnya ter-comment kini aktif, tanpa IPython
import base64, html as _html, io, math, time, warnings
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

warnings.filterwarnings("ignore")

# =========================================================
# 0. KONFIGURASI
# =========================================================
MU = "Rp"

PERIODE_DATA = "2y"
JENDELA_STRUKTUR = 250
PIVOT_ORDER = 7
FIB_LOOKBACK = 120
HARI_PROYEKSI = 20
N_SIM = 1500               # jalur Monte Carlo (FHS)
CACHE_TTL = 1800           # detik

MODE_GRAFIK = "ringkas"    # "ringkas" | "lengkap"

MIN_LIKUIDITAS = 10e9
MIN_RR = 1.5

MODAL = 100_000_000
RISIKO_PCT = 1.0
MAKS_POSISI_PCT = 25.0

ARB_PCT = 0.15

TOP_N = 5
MAKS_PER_SEKTOR = 2
MAKS_KORELASI = 0.80

KAT_KUAT = "🔥 BULLISH KUAT"
KAT_WATCH_BULL = "✅ BULLISH WATCHLIST"
KAT_REBOUND = "💡 REBOUND CANDIDATE"
KAT_WATCH = "⚠️ WATCHLIST"
KAT_NETRAL = "⚪ NETRAL"
KAT_AVOID = "❌ AVOID"
KAT_ILLIQ = "🚫 ILLIQUID"
KAT_LONG = (KAT_KUAT, KAT_WATCH_BULL, KAT_REBOUND)

IDX30_DEFAULT = [
    "BBCA.JK", "BBRI.JK", "BMRI.JK", "BBNI.JK", "TLKM.JK",
    "ASII.JK", "UNVR.JK", "ICBP.JK", "INDF.JK", "KLBF.JK",
    "ANTM.JK", "ADRO.JK", "PTBA.JK", "ITMG.JK", "INCO.JK",
    "MDKA.JK", "TPIA.JK", "BRPT.JK", "GOTO.JK", "ARTO.JK",
    "AMMN.JK", "MBMA.JK", "PGEO.JK", "PGAS.JK", "SMGR.JK",
    "INTP.JK", "CPIN.JK", "JPFA.JK", "EXCL.JK", "ISAT.JK",
]

SEKTOR = {
    "BBCA.JK": "Bank", "BBRI.JK": "Bank", "BMRI.JK": "Bank", "BBNI.JK": "Bank",
    "ARTO.JK": "Bank", "TLKM.JK": "Telko", "EXCL.JK": "Telko", "ISAT.JK": "Telko",
    "ASII.JK": "Otomotif", "UNVR.JK": "Konsumer", "ICBP.JK": "Konsumer",
    "INDF.JK": "Konsumer", "KLBF.JK": "Kesehatan", "ANTM.JK": "Logam",
    "INCO.JK": "Logam", "MDKA.JK": "Logam", "AMMN.JK": "Logam", "MBMA.JK": "Logam",
    "ADRO.JK": "Batubara", "PTBA.JK": "Batubara", "ITMG.JK": "Batubara",
    "TPIA.JK": "Petrokimia", "BRPT.JK": "Petrokimia", "GOTO.JK": "Teknologi",
    "PGEO.JK": "Energi", "PGAS.JK": "Energi", "SMGR.JK": "Semen", "INTP.JK": "Semen",
    "CPIN.JK": "Poultry", "JPFA.JK": "Poultry",
}

NAMA = {
    "BBCA.JK": "Bank Central Asia", "BBRI.JK": "Bank Rakyat Indonesia", "BMRI.JK": "Bank Mandiri",
    "BBNI.JK": "Bank Negara Indonesia", "TLKM.JK": "Telkom Indonesia", "ASII.JK": "Astra International",
    "UNVR.JK": "Unilever Indonesia", "ICBP.JK": "Indofood CBP", "INDF.JK": "Indofood Sukses Makmur",
    "KLBF.JK": "Kalbe Farma", "ANTM.JK": "Aneka Tambang", "ADRO.JK": "Adaro / Alamtri",
    "PTBA.JK": "Bukit Asam", "ITMG.JK": "Indo Tambangraya Megah", "INCO.JK": "Vale Indonesia",
    "MDKA.JK": "Merdeka Copper Gold", "TPIA.JK": "Chandra Asri", "BRPT.JK": "Barito Pacific",
    "GOTO.JK": "GoTo Gojek Tokopedia", "ARTO.JK": "Bank Jago", "AMMN.JK": "Amman Mineral",
    "MBMA.JK": "Merdeka Battery Materials", "PGEO.JK": "Pertamina Geothermal",
    "PGAS.JK": "Perusahaan Gas Negara", "SMGR.JK": "Semen Indonesia", "INTP.JK": "Indocement",
    "CPIN.JK": "Charoen Pokphand Indonesia", "JPFA.JK": "Japfa Comfeed", "EXCL.JK": "XL / XLSmart",
    "ISAT.JK": "Indosat Ooredoo Hutchison",
}


# =========================================================
# 1. UTILITAS, DATA (batch + cache), ATURAN IDX
# =========================================================
def _ok(x):
    return x is not None and not (isinstance(x, float) and np.isnan(x))


def _last(s):
    v = s.iloc[-1]
    return float(v) if not pd.isna(v) else np.nan


def normalisasi_kode(kode):
    kode = kode.strip().upper()
    if not any(ch in kode for ch in ".=^-"):
        kode += ".JK"
    return kode


def tick_size(h):
    if h < 200:   return 1
    if h < 500:   return 2
    if h < 2000:  return 5
    if h < 5000:  return 10
    return 25


def bulatkan_tick(h, mode="bawah"):
    t = tick_size(h)
    if mode == "bawah": return math.floor(h / t + 1e-9) * t
    if mode == "atas":  return math.ceil(h / t - 1e-9) * t
    return round(h / t) * t


def batas_arb(h):
    return bulatkan_tick(h * (1 - ARB_PCT), "atas")


def bar_masih_berjalan(tgl_terakhir):
    now = pd.Timestamp.now(tz="Asia/Jakarta")
    return (tgl_terakhir.date() == now.date() and now.weekday() < 5
            and (now.hour, now.minute) < (16, 15))


def _bersihkan(df, buang_bar_berjalan=True):
    idx = pd.to_datetime(df.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert("Asia/Jakarta").tz_localize(None)
    df = df.copy()
    df.index = idx
    if buang_bar_berjalan and len(df) and bar_masih_berjalan(df.index[-1]):
        df = df.iloc[:-1]
    return df


def _siapkan(df, buang_bar_berjalan=True):
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df = df[df["Volume"] > 0]
    return _bersihkan(df, buang_bar_berjalan)


# --- cache in-memory (hidup selama proses; Streamlit rerun tidak menghapusnya) ---
DATA_CACHE = {}


def _cache_get(key):
    v = DATA_CACHE.get(key)
    if v is not None and time.time() - v[0] < CACHE_TTL:
        return v[1]
    return None


def kosongkan_cache():
    DATA_CACHE.clear()


def prefetch_data(tickers, period=PERIODE_DATA):
    """Unduh SEMUA ticker dalam satu request paralel (jauh lebih cepat daripada
    satu-satu). Ticker gagal akan di-fetch ulang satuan oleh ambil_data()."""
    need = [t for t in dict.fromkeys(tickers) if _cache_get((t, period)) is None]
    if not need:
        return
    try:
        raw = yf.download(need, period=period, interval="1d", auto_adjust=False,
                          group_by="ticker", threads=True, progress=False)
    except Exception:
        return
    if raw is None or raw.empty:
        return
    multi = isinstance(raw.columns, pd.MultiIndex)
    for t in need:
        try:
            d = raw[t] if multi else raw
            d = _siapkan(d)
            if not d.empty:
                DATA_CACHE[(t, period)] = (time.time(), d)
        except Exception:
            pass


def ambil_data(ticker, period=PERIODE_DATA, buang_bar_berjalan=True):
    c = _cache_get((ticker, period))
    if c is not None:
        return c.copy()
    # auto_adjust=False: level harga = chart broker
    df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    if df is None or df.empty:
        raise ValueError(f"Data '{ticker}' kosong.")
    df = _siapkan(df, buang_bar_berjalan)
    if df.empty:
        raise ValueError(f"Data '{ticker}' kosong setelah dibersihkan.")
    DATA_CACHE[(ticker, period)] = (time.time(), df)
    return df.copy()


def ambil_ihsg(period=PERIODE_DATA, buang_bar_berjalan=True):
    c = _cache_get(("^JKSE", period))
    if c is not None:
        return c.copy()
    try:
        d = yf.Ticker("^JKSE").history(period=period, interval="1d", auto_adjust=False)
        if d is None or d.empty:
            return None
        s = _bersihkan(d[["Close"]].dropna(), buang_bar_berjalan)["Close"]
        DATA_CACHE[("^JKSE", period)] = (time.time(), s)
        return s.copy()
    except Exception:
        return None


def regime_ihsg(c):
    if c is None or len(c) < 200:
        return "NA"
    h, m50, m200 = c.iloc[-1], c.rolling(50).mean().iloc[-1], c.rolling(200).mean().iloc[-1]
    if h > m50 and h > m200: return "BULL"
    if h < m50 and h < m200: return "BEAR"
    return "NETRAL"


# =========================================================
# 2. STRUKTUR HARGA
# =========================================================
def cari_pivot(df, order=7):
    hi, lo, n = df["High"].values, df["Low"].values, len(df)
    ih, il = [], []
    for i in range(order, n - order):
        if hi[i] >= hi[i - order:i + order + 1].max():
            if not (ih and i - ih[-1] <= order and hi[i] == hi[ih[-1]]):
                ih.append(i)
        if lo[i] <= lo[i - order:i + order + 1].min():
            if not (il and i - il[-1] <= order and lo[i] == lo[il[-1]]):
                il.append(i)
    return np.array(ih, dtype=int), np.array(il, dtype=int)


def cari_trendline(harga, pivots, jenis, toleransi=0.015, max_pivot=8,
                   maks_tembus=2, min_jarak=5, maks_jarak=0.12):
    n = len(harga); pv = list(pivots[-max_pivot:])
    terbaik, skor_terbaik = None, -1e9
    for a in range(len(pv) - 1):
        for b in range(a + 1, len(pv)):
            i, j = pv[a], pv[b]
            if j - i < min_jarak: continue
            slope = (harga[j] - harga[i]) / (j - i)
            xs = np.arange(i, n)
            garis = harga[i] + slope * (xs - i)
            if garis.min() <= 0: continue
            if abs(garis[-1] - harga[-1]) / harga[-1] > maks_jarak: continue
            selisih = (harga[i:] - garis) / garis
            tembus = int((selisih > toleransi).sum() if jenis == "resistance"
                         else (selisih < -toleransi).sum())
            if tembus > maks_tembus: continue
            sentuhan = sum(1 for p in pv if p >= i and
                           abs(harga[p] - (harga[i] + slope * (p - i))) /
                           (harga[i] + slope * (p - i)) <= toleransi)
            skor = sentuhan * 10 - tembus * 5 + (j - i) / n * 5 + j / n * 5
            if skor > skor_terbaik:
                skor_terbaik = skor
                terbaik = {"i": int(i), "y0": float(harga[i]),
                           "slope": float(slope), "sentuhan": sentuhan}
    return terbaik


def klasifikasi_trend(res, sup, harga, batas=0.0005):
    if res is None and sup is None: return "Trend line belum terbentuk"
    def arah(t):
        if t is None: return None
        rel = t["slope"] / harga
        return "naik" if rel > batas else ("turun" if rel < -batas else "datar")
    r, s = arah(res), arah(sup)
    if r == "naik" and s == "naik":   return "UPTREND"
    if r == "turun" and s == "turun": return "DOWNTREND"
    if r == "turun" and s == "naik":  return "Symmetrical Triangle"
    if r == "datar" and s == "naik":  return "Ascending Triangle"
    if r == "turun" and s == "datar": return "Descending Triangle"
    if r == "datar" and s == "datar": return "SIDEWAYS"
    if r == "naik" and s in ("datar", "turun"): return "Rising Wedge"
    if s == "turun" and r in ("datar", "naik"): return "Melebar ke bawah"
    if r is None: return f"Hanya support (arah: {s})"
    return f"Hanya resistance (arah: {r})"


def cari_support_resistance(df, idx_high, idx_low, toleransi=0.02,
                            min_sentuh=2, jumlah=3):
    harga = float(df["Close"].iloc[-1])
    titik = [float(df["High"].iloc[i]) for i in idx_high] + \
            [float(df["Low"].iloc[i]) for i in idx_low]
    titik.sort()
    klaster = []
    for p in titik:
        if klaster and abs(p - np.mean(klaster[-1])) / np.mean(klaster[-1]) <= toleransi:
            klaster[-1].append(p)
        else:
            klaster.append([p])
    level = [(float(np.mean(k)), len(k)) for k in klaster]
    def pilih(kandidat, reverse):
        kuat = [l for l in kandidat if l[1] >= min_sentuh]
        pakai = kuat if kuat else kandidat
        pakai = sorted(pakai, key=lambda l: abs(l[0] - harga))[:jumlah]
        return sorted(pakai, key=lambda l: l[0], reverse=reverse)
    return (pilih([l for l in level if l[0] < harga], True),
            pilih([l for l in level if l[0] >= harga], False))


def _sanitize_sr(levels, harga, batas_pct=25.0):
    return [(l, s) for l, s in levels if abs(l - harga) / harga * 100 <= batas_pct]


RASIO_FIB = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)
EKSTENSI_FIB = (1.272, 1.618)


def hitung_fibonacci(df, lookback=120):
    lookback = min(lookback, len(df))
    n0 = len(df) - lookback
    seg = df.iloc[n0:]
    ih = int(np.argmax(seg["High"].values)) + n0
    il = int(np.argmin(seg["Low"].values)) + n0
    H, L = float(df["High"].iloc[ih]), float(df["Low"].iloc[il])
    rentang = H - L
    if rentang <= 0: return None
    naik = il < ih
    if naik:
        level = {r: H - r * rentang for r in RASIO_FIB}
        ekstensi = {e: L + e * rentang for e in EKSTENSI_FIB}
    else:
        level = {r: L + r * rentang for r in RASIO_FIB}
        ekstensi = {e: H - e * rentang for e in EKSTENSI_FIB}
    return {"naik": naik, "i_high": ih, "i_low": il, "H": H, "L": L,
            "level": level, "ekstensi": ekstensi}


# =========================================================
# 3. VOLUME
# =========================================================
RVOL_OUTLIER = 5.0


def _nilai_break(arah, t, arr, close, rvol, n, konfirmasi=3):
    kembali = False
    for u in range(t + 1, min(t + konfirmasi, n - 1) + 1):
        if arah == "naik" and close[u] < arr[u]: kembali = True; break
        if arah == "turun" and close[u] > arr[u]: kembali = True; break
    r = rvol[t]
    if kembali:
        kode = "palsu"
        status = "FALSE BREAKOUT (bull trap)" if arah == "naik" else "FALSE BREAKDOWN (bear trap)"
    elif np.isnan(r):
        kode, status = "netral", "volume belum bisa dinilai"
    elif r >= 1.5:
        kode, status = "valid", "VALID: volume kuat"
    elif r < 1.0:
        kode, status = "curiga", "MENCURIGAKAN: volume lemah"
    else:
        kode, status = "netral", "NETRAL: volume biasa"
    return kode, status


def analisa_volume(df, support, resistance, res_line, sup_line,
                   lookback=15, konfirmasi=3, buf=0.002):
    vol = df["Volume"].astype(float)
    if vol.sum() <= 0 or (vol > 0).mean() < 0.5: return None
    close = df["Close"].values; high = df["High"].values; low = df["Low"].values
    n = len(df)
    vma20 = vol.shift(1).rolling(20).mean()
    rvol = (vol / vma20).values
    arah_h = np.sign(df["Close"].diff().fillna(0).values)
    obv = np.cumsum(arah_h * vol.values)

    garis = [(f"S/R {MU} {lv:,.0f}", np.full(n, lv), "dua")
             for lv, _ in list(resistance) + list(support)]
    xs = np.arange(n)
    if res_line:
        arr = res_line["y0"] + res_line["slope"] * (xs - res_line["i"])
        garis.append(("Trend line resistance", np.where(xs > res_line["i"], arr, np.nan), "atas"))
    if sup_line:
        arr = sup_line["y0"] + sup_line["slope"] * (xs - sup_line["i"])
        garis.append(("Trend line support", np.where(xs > sup_line["i"], arr, np.nan), "bawah"))

    events = []; mulai = max(n - lookback, 1)
    for nama, arr, mode in garis:
        kandidat = []
        for t in range(mulai, n):
            L, Lp = arr[t], arr[t - 1]
            if np.isnan(L) or np.isnan(Lp): continue
            naik = close[t] > L * (1 + buf) and close[t - 1] <= Lp * (1 + buf)
            turun = close[t] < L * (1 - buf) and close[t - 1] >= Lp * (1 - buf)
            if naik and mode in ("dua", "atas"):
                kode, status = _nilai_break("naik", t, arr, close, rvol, n, konfirmasi)
                kandidat.append((t, 1, "Breakout naik", kode, status))
            elif turun and mode in ("dua", "bawah"):
                kode, status = _nilai_break("turun", t, arr, close, rvol, n, konfirmasi)
                kandidat.append((t, 1, "Breakdown", kode, status))
            else:
                r = rvol[t]
                kuat = (not np.isnan(r)) and r >= 1.3
                if (mode in ("dua", "atas") and high[t] > L * (1 + 0.003)
                        and close[t] < L and close[t - 1] < Lp):
                    kandidat.append((t, 0, "Sumbu atas", "tolak",
                                     "Penolakan " + ("KUAT" if kuat else "lemah")))
                elif (mode in ("dua", "bawah") and low[t] < L * (1 - 0.003)
                        and close[t] > L and close[t - 1] > Lp):
                    kandidat.append((t, 0, "Sumbu bawah", "tolak",
                                     "Penolakan " + ("KUAT" if kuat else "lemah")))
        crosses = [k for k in kandidat if k[1] == 1]
        wicks = [k for k in kandidat if k[1] == 0][-1:]
        for t, _, jenis, kode, status in crosses + wicks:
            events.append({"t": t, "tanggal": df.index[t].date(), "nama": nama,
                           "jenis": jenis, "kode": kode, "status": status,
                           "rvol": float(rvol[t]) if not np.isnan(rvol[t]) else np.nan,
                           "harga": float(close[t])})
    events.sort(key=lambda e: e["t"], reverse=True)
    events = events[:8]

    w = 20; div = None
    if n >= 2 * w + 1:
        if high[-w:].max() > high[-2 * w:-w].max() and obv[-w:].max() < obv[-2 * w:-w].max():
            div = ("bearish", "Divergence BEARISH")
        elif low[-w:].min() < low[-2 * w:-w].min() and obv[-w:].min() > obv[-2 * w:-w].min():
            div = ("bullish", "Divergence BULLISH")

    k = min(10, n - 1)
    ret = close[-1] / close[-k - 1] - 1
    v_k = vol.values[-k:]
    m_naik, m_turun = arah_h[-k:] > 0, arah_h[-k:] < 0
    vn = v_k[m_naik].mean() if m_naik.any() else 0.0
    vt = v_k[m_turun].mean() if m_turun.any() else 0.0
    rasio = (vn / vt) if vt > 0 else (np.inf if vn > 0 else np.nan)
    rasio_jual = (vt / vn) if vn > 0 else (np.inf if vt > 0 else np.nan)

    if ret > 0.02:
        if (rasio >= 1.2) and not (div and div[0] == "bearish"):
            verdict = "KENAIKAN didukung volume (sehat)"
        elif rasio < 1.0 or (div and div[0] == "bearish"):
            verdict = "KENAIKAN RAWAN PALSU"
        else:
            verdict = "Kenaikan volume biasa: netral"
    elif ret < -0.02:
        if (rasio_jual >= 1.2) and not (div and div[0] == "bullish"):
            verdict = "PENURUNAN didukung volume (tekanan jual nyata)"
        elif rasio_jual < 1.0 or (div and div[0] == "bullish"):
            verdict = "PENURUNAN RAWAN PALSU: potensi rebound"
        else:
            verdict = "Penurunan volume biasa: netral"
    else:
        verdict = "Sideways: volume belum memberi arah"
    if any(e["kode"] == "palsu" for e in events):
        verdict += " | ada FALSE BREAK"

    r_now = rvol[-1]
    return {"rvol": rvol, "obv": obv, "events": events, "div": div, "ret": ret,
            "rasio": rasio, "rasio_jual": rasio_jual, "k": k, "verdict": verdict,
            "vol_now": float(vol.iloc[-1]), "vma_now": float(vma20.iloc[-1]),
            "r_now": float(r_now) if not np.isnan(r_now) else np.nan}


# =========================================================
# 4. INDIKATOR
# =========================================================
def hitung_rsi(close, n=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.where(loss > 0, other=np.where(gain > 0, 100.0, 50.0))
    return rsi


def _true_range(df):
    high, low, close = df["High"], df["Low"], df["Close"]
    return pd.concat([high - low, (high - close.shift()).abs(),
                      (low - close.shift()).abs()], axis=1).max(axis=1)


def hitung_atr(df, n=14):
    return _true_range(df).ewm(alpha=1/n, adjust=False).mean()


def hitung_bollinger(close, n=20, k=2.0):
    ma = close.rolling(n).mean()
    sd = close.rolling(n).std()
    upper, lower = ma + k * sd, ma - k * sd
    bandwidth = (upper - lower) / ma
    pct_b = (close - lower) / (upper - lower)
    return ma, upper, lower, bandwidth, pct_b


def hitung_adx(df, n=14):
    high, low = df["High"], df["Low"]
    up, down = high.diff(), -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=high.index)
    atr = _true_range(df).ewm(alpha=1/n, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/n, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1/n, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1/n, adjust=False).mean()
    return adx, plus_di, minus_di


def hitung_vwma(df, n=20):
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    return (tp * df["Volume"]).rolling(n).sum() / df["Volume"].rolling(n).sum()


def hitung_avwap(df, pos_anchor):
    seg = df.iloc[pos_anchor:]
    tp = (seg["High"] + seg["Low"] + seg["Close"]) / 3
    v = seg["Volume"].astype(float)
    return (tp * v).cumsum() / v.cumsum()


def tren_mingguan(df):
    w = df["Close"].resample("W-FRI").last().dropna()
    if len(w) < 32: return None
    ma10, ma30 = w.rolling(10).mean().iloc[-1], w.rolling(30).mean().iloc[-1]
    c = w.iloc[-1]
    if c > ma10 and ma10 > ma30: return "UP"
    if c < ma10 and ma10 < ma30: return "DOWN"
    return "NETRAL"


# =========================================================
# 5. PRICE ACTION
# =========================================================
def deteksi_candlestick(df):
    n = len(df)
    if n < 8: return []
    o, h, l, c = (df[k].values for k in ("Open", "High", "Low", "Close"))
    t = n - 1
    body, rng = abs(c[t] - o[t]), h[t] - l[t]
    if rng == 0: return []
    upper = h[t] - max(c[t], o[t]); lower = min(c[t], o[t]) - l[t]
    turun_sebelum = c[t - 1] < c[t - 6] * 0.98
    naik_sebelum = c[t - 1] > c[t - 6] * 1.02
    body_prev = abs(c[t - 1] - o[t - 1])

    if body / rng < 0.1:
        return [{"nama": "Doji", "arah": "netral", "tipe": "reversal", "valid": False}]
    if (c[t] > o[t] and c[t - 1] < o[t - 1] and c[t] > o[t - 1]
            and o[t] < c[t - 1] and body > body_prev):
        return [{"nama": "Bullish Engulfing", "arah": "bullish", "tipe": "reversal",
                 "valid": bool(turun_sebelum)}]
    if (c[t] < o[t] and c[t - 1] > o[t - 1] and c[t] < o[t - 1]
            and o[t] > c[t - 1] and body > body_prev):
        return [{"nama": "Bearish Engulfing", "arah": "bearish", "tipe": "reversal",
                 "valid": bool(naik_sebelum)}]
    if lower > 2 * body and upper < body:
        return [{"nama": "Hammer", "arah": "bullish", "tipe": "reversal",
                 "valid": bool(turun_sebelum)}]
    if upper > 2 * body and lower < body:
        return [{"nama": "Shooting Star", "arah": "bearish", "tipe": "reversal",
                 "valid": bool(naik_sebelum)}]
    if body / rng > 0.9:
        bull = c[t] > o[t]
        return [{"nama": "Bullish Marubozu" if bull else "Bearish Marubozu",
                 "arah": "bullish" if bull else "bearish",
                 "tipe": "kontinuasi", "valid": True}]
    return []


def analisa_market_structure(df, idx_high, idx_low, n_pivot=3):
    kosong = {"struktur": "tidak jelas", "bos": None, "choch": None, "event": None}
    if len(idx_high) < 2 or len(idx_low) < 2:
        return kosong
    hv = [float(df["High"].iloc[i]) for i in idx_high[-n_pivot:]]
    lv = [float(df["Low"].iloc[i]) for i in idx_low[-n_pivot:]]
    hh = all(hv[i] > hv[i-1] for i in range(1, len(hv)))
    hl = all(lv[i] > lv[i-1] for i in range(1, len(lv)))
    lh = all(hv[i] < hv[i-1] for i in range(1, len(hv)))
    ll = all(lv[i] < lv[i-1] for i in range(1, len(lv)))
    if hh and hl:   struktur = "Uptrend (HH+HL)"
    elif lh and ll: struktur = "Downtrend (LH+LL)"
    else:           struktur = "Mixed / Ranging"

    harga = float(df["Close"].iloc[-1])
    naik_tembus, turun_tembus = harga > hv[-1], harga < lv[-1]
    bos = choch = event = None
    if "Uptrend" in struktur:
        if turun_tembus:
            choch = "CHoCH bearish (potensi reversal)"; event = "bearish"
        elif naik_tembus:
            bos = "BOS bullish (lanjutan tren)"; event = "bullish"
    elif "Downtrend" in struktur:
        if naik_tembus:
            choch = "CHoCH bullish (potensi reversal)"; event = "bullish"
        elif turun_tembus:
            bos = "BOS bearish (lanjutan tren)"; event = "bearish"
    else:
        if naik_tembus:
            bos = "BOS bullish (tembus high terakhir)"; event = "bullish"
        elif turun_tembus:
            bos = "BOS bearish (tembus low terakhir)"; event = "bearish"
    return {"struktur": struktur, "bos": bos, "choch": choch, "event": event}


def deteksi_hidden_divergence(df, idx_high, idx_low, series_ind,
                              jarak_min=5, jarak_maks=60, maks_umur=30):
    n = len(df)
    hasil = []
    if n < 30: return hasil
    hi, lo, cl = df["High"].values, df["Low"].values, df["Close"].values
    for nama, arr in series_ind.items():
        mg = 2.0 if nama == "RSI" else 0.02 * (np.nanmax(arr) - np.nanmin(arr))
        if len(idx_low) >= 2:
            p1, p2 = int(idx_low[-2]), int(idx_low[-1])
            if (jarak_min <= p2 - p1 <= jarak_maks and n - 1 - p2 <= maks_umur
                    and not (np.isnan(arr[p1]) or np.isnan(arr[p2]))
                    and lo[p2] > lo[p1] * 1.002 and arr[p2] < arr[p1] - mg):
                hasil.append({
                    "arah": "bullish", "indikator": nama, "i1": p1, "i2": p2,
                    "tgl1": df.index[p1].date(), "tgl2": df.index[p2].date(),
                    "harga1": float(lo[p1]), "harga2": float(lo[p2]),
                    "ind1": float(arr[p1]), "ind2": float(arr[p2]),
                    "invalid": bool((cl[p2:] < lo[p1]).any()),
                    "konfirmasi": bool(p2 < n - 2 and cl[-1] > hi[p2 + 1:-1].max()),
                    "umur": n - 1 - p2})
        if len(idx_high) >= 2:
            p1, p2 = int(idx_high[-2]), int(idx_high[-1])
            if (jarak_min <= p2 - p1 <= jarak_maks and n - 1 - p2 <= maks_umur
                    and not (np.isnan(arr[p1]) or np.isnan(arr[p2]))
                    and hi[p2] < hi[p1] * 0.998 and arr[p2] > arr[p1] + mg):
                hasil.append({
                    "arah": "bearish", "indikator": nama, "i1": p1, "i2": p2,
                    "tgl1": df.index[p1].date(), "tgl2": df.index[p2].date(),
                    "harga1": float(hi[p1]), "harga2": float(hi[p2]),
                    "ind1": float(arr[p1]), "ind2": float(arr[p2]),
                    "invalid": bool((cl[p2:] > hi[p1]).any()),
                    "konfirmasi": bool(p2 < n - 2 and cl[-1] < lo[p2 + 1:-1].min()),
                    "umur": n - 1 - p2})
    return hasil


def hitung_rs(close_saham, close_ihsg):
    if close_ihsg is None or len(close_ihsg) < 70:
        return None
    ih = close_ihsg.reindex(close_saham.index).ffill()
    ok = ih.notna()
    s, i = close_saham[ok], ih[ok]
    if len(s) < 70: return None
    ret = lambda x, n: x.iloc[-1] / x.iloc[-n - 1] - 1
    ratio = s / i
    rma = ratio.rolling(50).mean().iloc[-1]
    return {"rs_20": float((ret(s, 20) - ret(i, 20)) * 100),
            "rs_60": float((ret(s, 60) - ret(i, 60)) * 100),
            "rs_trend": bool(ratio.iloc[-1] > rma) if not np.isnan(rma) else None}


# =========================================================
# 7. RISK
# =========================================================
def hitung_stop_target(harga, atr, support_list, resistance_list):
    if not _ok(atr) or atr <= 0:
        return None
    s_lv = [l for l, _ in support_list if l < harga]
    r_lv = [l for l, _ in resistance_list if l > harga]
    sl_awal = (s_lv[0] - 0.25 * atr) if s_lv else harga - 1.5 * atr
    jarak = float(np.clip(harga - sl_awal, 1.0 * atr, 3.0 * atr))
    sl = bulatkan_tick(harga - jarak, "bawah")
    tp1 = r_lv[0] if r_lv else harga + 2 * atr
    tp2 = r_lv[1] if len(r_lv) > 1 else max(tp1, harga + 3 * atr)
    tp1 = bulatkan_tick(tp1, "bawah")
    tp2 = bulatkan_tick(max(tp2, tp1), "bawah")
    risk, reward = harga - sl, tp1 - harga
    rr = (reward / risk) if (risk > 0 and reward > 0) else 0.0
    return {"sl": float(sl), "tp1": float(tp1), "tp2": float(tp2), "rr": float(rr),
            "sl_pct": float(risk / harga * 100), "atr_pct": float(atr / harga * 100),
            "jarak_sl_atr": float(risk / atr)}


def hitung_posisi(harga, sl, modal=None, risiko_pct=None, maks_pct=None):
    modal = MODAL if modal is None else modal
    risiko_pct = RISIKO_PCT if risiko_pct is None else risiko_pct
    maks_pct = MAKS_POSISI_PCT if maks_pct is None else maks_pct
    if sl is None or sl >= harga:
        return None
    risk_saham = harga - sl
    lot_risiko = math.floor(modal * risiko_pct / 100 / risk_saham / 100)
    lot_maks = math.floor(modal * maks_pct / 100 / harga / 100)
    lot = max(0, min(lot_risiko, lot_maks))
    arb = batas_arb(harga)
    return {"lot": lot, "nilai": lot * 100 * harga,
            "risiko_rp": lot * 100 * risk_saham,
            "batas_arb": arb,
            "rugi_arb_pct_modal": lot * 100 * (harga - arb) / modal * 100}


# =========================================================
# 8. FITUR
# =========================================================
def hitung_fitur(df_full, ihsg_close=None):
    if df_full is None or len(df_full) < 120:
        return None
    view = df_full.tail(JENDELA_STRUKTUR)
    close = df_full["Close"]
    harga = float(close.iloc[-1])

    idx_high, idx_low = cari_pivot(view, PIVOT_ORDER)
    res_line = cari_trendline(view["High"].values, idx_high, "resistance")
    sup_line = cari_trendline(view["Low"].values, idx_low, "support")
    support_raw, resistance_raw = cari_support_resistance(view, idx_high, idx_low)
    support = _sanitize_sr(support_raw, harga)
    resistance = _sanitize_sr(resistance_raw, harga)
    judul_trend = klasifikasi_trend(res_line, sup_line, harga)
    vol = analisa_volume(view, support, resistance, res_line, sup_line)
    fib = hitung_fibonacci(view, FIB_LOOKBACK)
    ms = analisa_market_structure(view, idx_high, idx_low)
    candles = deteksi_candlestick(view)
    _rsi_full = hitung_rsi(df_full["Close"])
    _obv_full = np.cumsum(np.sign(df_full["Close"].diff().fillna(0).values)
                          * df_full["Volume"].astype(float).values)
    hidden_div = deteksi_hidden_divergence(
        view, idx_high, idx_low,
        {"RSI": _rsi_full.tail(len(view)).values, "OBV": _obv_full[-len(view):]})

    rsi = _last(_rsi_full)
    ma20, ma50, ma200 = (close.rolling(n).mean() for n in (20, 50, 200))
    ma50_slope = float(ma50.iloc[-1] - ma50.iloc[-6]) if len(ma50.dropna()) > 6 else np.nan
    atr = _last(hitung_atr(df_full))
    _, bb_up, bb_lo, bb_bw, bb_pctb = hitung_bollinger(close)
    bw_hist = bb_bw.dropna().tail(120)
    bb_width = _last(bb_bw)
    bb_squeeze = bool(bb_width <= bw_hist.quantile(0.2)) if len(bw_hist) > 20 else False
    adx_s, pdi, mdi = hitung_adx(df_full)
    vwma = _last(hitung_vwma(df_full))
    mingguan = tren_mingguan(df_full)

    avwap = np.nan
    if fib is not None:
        off = len(df_full) - len(view)
        anchor = off + (fib["i_low"] if fib["naik"] else fib["i_high"])
        avwap = _last(hitung_avwap(df_full, anchor))

    ret_126 = float((close.iloc[-1] / close.iloc[-127] - 1) * 100) if len(close) >= 127 else np.nan
    mom_12_1 = (float((close.iloc[-22] / close.iloc[-253] - 1) * 100)
                if len(close) >= 253 else np.nan)
    jarak_52w = float((harga / df_full["High"].tail(252).max() - 1) * 100)

    rs = hitung_rs(close, ihsg_close)
    reg_ihsg = regime_ihsg(ihsg_close)
    nilai_transaksi = float((df_full["Close"] * df_full["Volume"]).tail(20).mean())

    s1 = support[0][0] if support else None
    r1 = resistance[0][0] if resistance else None
    jarak_s = ((harga - s1) / harga * 100) if s1 else None
    jarak_r = ((r1 - harga) / harga * 100) if r1 else None

    di_gz, kedalaman = False, None
    if fib is not None:
        lo_, hi_ = sorted((fib["level"][0.5], fib["level"][0.618]))
        di_gz = lo_ <= harga <= hi_
        rentang = fib["H"] - fib["L"]
        kedalaman = ((fib["H"] - harga) if fib["naik"] else (harga - fib["L"])) / rentang * 100

    n_v = len(view)
    ev = vol["events"] if vol else []
    baru = [e for e in ev if e["t"] >= n_v - 5]
    rvol_now = vol["r_now"] if vol else np.nan

    return {
        "harga": harga, "trend": judul_trend,
        "rsi": rsi, "ma20": _last(ma20), "ma50": _last(ma50), "ma200": _last(ma200),
        "ma50_slope": ma50_slope, "mingguan": mingguan,
        "atr": atr, "atr_pct": (atr / harga * 100) if _ok(atr) else None,
        "bb_upper": _last(bb_up), "bb_lower": _last(bb_lo), "bb_width": bb_width,
        "bb_pctb": _last(bb_pctb), "bb_squeeze": bb_squeeze,
        "adx": _last(adx_s), "di_plus": _last(pdi), "di_minus": _last(mdi),
        "vwma": vwma, "avwap": avwap,
        "candles": candles, "market_structure": ms, "hidden_div": hidden_div,
        "rs": rs, "regime_ihsg": reg_ihsg,
        "ret_126": ret_126, "mom_12_1": mom_12_1, "jarak_52w": jarak_52w,
        "nilai_transaksi": nilai_transaksi,
        "vol_verdict": vol["verdict"] if vol else "n/a",
        "vol_rvol": rvol_now,
        "rvol_outlier": bool(_ok(rvol_now) and rvol_now > RVOL_OUTLIER),
        "vol_div": (vol["div"][0] if vol and vol["div"] else None),
        "brk_valid_up": any(e["jenis"] == "Breakout naik" and e["kode"] == "valid" for e in baru),
        "brk_valid_dn": any(e["jenis"] == "Breakdown" and e["kode"] == "valid" for e in baru),
        "fb_up": any(e["jenis"] == "Breakout naik" and e["kode"] == "palsu" for e in ev),
        "fb_dn": any(e["jenis"] == "Breakdown" and e["kode"] == "palsu" for e in ev),
        "support": s1, "resistance": r1,
        "jarak_support_pct": jarak_s, "jarak_resistance_pct": jarak_r,
        "fib_naik": (fib["naik"] if fib else None),
        "fib_kedalaman_pct": kedalaman, "di_golden_zone": di_gz,
        "stop_target": hitung_stop_target(harga, atr, support, resistance),
        "support_list": support, "resistance_list": resistance,
        "res_line": res_line, "sup_line": sup_line, "fib": fib, "vol": vol,
    }


# =========================================================
# 9. SKORING (tidak berubah dari v4.1)
# =========================================================
def _cap(x, m):
    return max(-m, min(m, x))


def skor_rekomendasi(f):
    alasan, tanda = [], []

    def _a(t, teks):
        alasan.append(teks); tanda.append(t)

    harga = f["harga"]
    adx, dip, dim = f["adx"], f["di_plus"], f["di_minus"]
    ada_adx = _ok(adx)
    regime = "TREND" if ada_adx and adx >= 25 else ("RANGE" if ada_adx and adx < 20 else "MIX")
    arah_di = 0
    if _ok(dip) and _ok(dim):
        arah_di = 1 if dip > dim else -1

    # ---- T ----
    T = 0
    if _ok(f["ma200"]):
        if harga > f["ma200"]: T += 1; _a(+1, "> MA200")
        else:                  T -= 1; _a(-1, "< MA200")
    if _ok(f["ma50"]) and _ok(f["ma50_slope"]):
        if f["ma20"] > f["ma50"] and f["ma50_slope"] > 0: T += 1; _a(+1, "MA20>MA50 & MA50 naik")
        elif f["ma20"] < f["ma50"] and f["ma50_slope"] < 0: T -= 1; _a(-1, "MA20<MA50 & MA50 turun")
    tr = f["trend"]
    if "UPTREND" in tr or "Ascending" in tr:      T += 1; _a(+1, "trendline naik")
    elif "DOWNTREND" in tr or "Descending" in tr: T -= 1; _a(-1, "trendline turun")
    ms = f["market_structure"]
    if "Uptrend" in ms["struktur"]:     T += 1; _a(+1, "struktur HH+HL")
    elif "Downtrend" in ms["struktur"]: T -= 1; _a(-1, "struktur LH+LL")
    if ms["event"]:
        nama = ms["choch"] or ms["bos"]
        T += 1 if ms["event"] == "bullish" else -1
        _a(1 if ms["event"] == "bullish" else -1, nama.split(" (")[0])
    if f["mingguan"] == "UP":     T += 1; _a(+1, "mingguan naik")
    elif f["mingguan"] == "DOWN": T -= 1; _a(-1, "mingguan turun")
    T = _cap(T, 5)

    # ---- M ----
    M = 0
    if ada_adx and adx >= 25 and arah_di != 0:
        M += arah_di
        _a(arah_di, f"ADX {adx:.0f} " + ("DI+ dominan" if arah_di > 0 else "DI- dominan"))
    elif ada_adx and adx < 20:
        _a(0, f"ADX {adx:.0f} sideways")
    r = f["rsi"]
    ada_ma = _ok(f["ma50"]) and _ok(f["ma200"])
    up_reg = ada_ma and harga > f["ma50"] > f["ma200"]
    dn_reg = ada_ma and harga < f["ma50"] < f["ma200"]
    if up_reg:
        if 45 <= r <= 80: M += 1; _a(+1, "RSI zona sehat (uptrend)")
        elif r < 40:      M -= 1; _a(-1, "RSI lemah untuk uptrend")
        elif r > 85:      M -= 1; _a(-1, "RSI ekstrem")
    elif dn_reg:
        if r <= 50:  M -= 1; _a(-1, "RSI lemah (downtrend)")
        elif r >= 60: M += 1; _a(+1, "RSI kuat di downtrend")
    else:
        if r >= 55:   M += 1; _a(+1, "RSI >= 55")
        elif r <= 45: M -= 1; _a(-1, "RSI <= 45")
    if _ok(f["ret_126"]):
        if f["ret_126"] > 10:    M += 1; _a(+1, f"momentum 6b {f['ret_126']:+.0f}%")
        elif f["ret_126"] < -10: M -= 1; _a(-1, f"momentum 6b {f['ret_126']:+.0f}%")
    rs = f.get("rs") or {}
    if _ok(rs.get("rs_20")) and _ok(rs.get("rs_60")):
        if rs["rs_20"] > 3 and rs["rs_60"] > 0:
            M += 1; _a(+1, f"RS+ vs IHSG {rs['rs_20']:+.1f}%")
        elif rs["rs_20"] < -5 and rs["rs_60"] < 0:
            M -= 1; _a(-1, f"RS- vs IHSG {rs['rs_20']:+.1f}%")
    M = _cap(M, 4)

    # ---- V ----
    V = 0
    vol = f["vol_verdict"] or ""
    if f["rvol_outlier"]:
        _a(0, "RVOL outlier (cek pasar nego) → volume tak dinilai")
    else:
        if "KENAIKAN didukung volume" in vol:      V += 1; _a(+1, "kenaikan didukung volume")
        elif "KENAIKAN RAWAN PALSU" in vol:        V -= 1; _a(-1, "kenaikan rawan palsu")
        elif "PENURUNAN didukung volume" in vol:   V -= 1; _a(-1, "tekanan jual nyata")
        if f["brk_valid_up"]: V += 1; _a(+1, "breakout valid (volume)")
        if f["brk_valid_dn"]: V -= 1; _a(-1, "breakdown valid (volume)")
    if f["fb_up"]: V -= 1; _a(-1, "false breakout (bull trap)")
    if f["fb_dn"]: V += 1; _a(+1, "false breakdown (bear trap)")
    V = _cap(V, 2)

    # ---- S ----
    S = 0
    js, jr = f["jarak_support_pct"], f["jarak_resistance_pct"]
    dekat_s = js is not None and 0 <= js < 3
    dekat_r = jr is not None and 0 <= jr < 1.5
    pb = f["bb_pctb"]
    mr_bawah = int(r < 35) + int(_ok(pb) and pb < 0.05) + int(dekat_s)
    mr_atas = int(r > 70) + int(_ok(pb) and pb > 0.95) + int(dekat_r)
    bias_tm = T + M

    if regime == "RANGE":
        if mr_bawah:
            S += min(2, mr_bawah); _a(+1, f"range: klaster oversold/support ({mr_bawah})")
        if mr_atas:
            S -= min(2, mr_atas); _a(-1, f"range: klaster overbought/resistance ({mr_atas})")
    elif regime == "TREND":
        if arah_di > 0:
            if dekat_s: S += 1; _a(+1, "pullback ke support dalam tren naik")
            if dekat_r: S -= 1; _a(-1, "mentok resistance")
        else:
            if dekat_r: S -= 1; _a(-1, "retest resistance dalam tren turun")
    else:
        if mr_bawah >= 2:            S += 1; _a(+1, "klaster oversold/support")
        elif dekat_s and bias_tm >= 2: S += 1; _a(+1, "dekat support + bias naik")
        if mr_atas >= 2:             S -= 1; _a(-1, "klaster overbought/resistance")

    if f["di_golden_zone"]:
        if f["fib_naik"] and not (regime == "TREND" and arah_di < 0):
            S += 1; _a(+1, "golden zone (retracement swing naik)")
        elif not f["fib_naik"]:
            S -= 1; _a(-1, "golden zone swing turun = resistance")
    if _ok(f["avwap"]):
        if harga > f["avwap"]: S += 1; _a(+1, "> AVWAP swing")
        else:                  S -= 1; _a(-1, "< AVWAP swing")
    rv = f["vol_rvol"]
    for c in f["candles"]:
        if not c["valid"]: continue
        if c["tipe"] == "reversal":
            if c["arah"] == "bullish" and (dekat_s or (_ok(pb) and pb < 0.2) or f["di_golden_zone"]):
                S += 1; _a(+1, f"{c['nama']} di area support")
            elif c["arah"] == "bearish" and (dekat_r or (_ok(pb) and pb > 0.8)):
                S -= 1; _a(-1, f"{c['nama']} di area resistance")
        elif _ok(rv) and rv >= 1.3 and not f["rvol_outlier"]:
            S += 1 if c["arah"] == "bullish" else -1
            _a(1 if c["arah"] == "bullish" else -1, f"{c['nama']} + volume")
    hd_dipakai = None
    hd = [d for d in (f.get("hidden_div") or []) if not d["invalid"]]
    if hd and regime != "RANGE":
        ma50_ok = _ok(f["ma50"]) and _ok(f["ma50_slope"])
        ctx_naik = ma50_ok and harga > f["ma50"] and (
            "Uptrend" in ms["struktur"] or f["ma50_slope"] > 0)
        ctx_turun = ma50_ok and harga < f["ma50"] and (
            "Downtrend" in ms["struktur"] or f["ma50_slope"] < 0)
        dekat_ma = any(_ok(x) and abs(harga / x - 1) < 0.03 for x in (f["ma20"], f["ma50"]))
        bull_hd = [d for d in hd if d["arah"] == "bullish"]
        bear_hd = [d for d in hd if d["arah"] == "bearish"]
        if bull_hd and ctx_naik and (dekat_s or dekat_ma or
                                     (f["di_golden_zone"] and f["fib_naik"])):
            S += 1; hd_dipakai = "bullish"
            _a(1, "hidden bullish div (" + "+".join(d["indikator"] for d in bull_hd)
                  + ") di area pullback")
            if any(d["konfirmasi"] for d in bull_hd):
                S += 1; _a(+1, "hidden div terkonfirmasi (breakout minor)")
        elif bear_hd and ctx_turun and (dekat_r or dekat_ma):
            S -= 1; hd_dipakai = "bearish"
            _a(-1, "hidden bearish div (" + "+".join(d["indikator"] for d in bear_hd)
                  + ") di area rally")
            if any(d["konfirmasi"] for d in bear_hd):
                S -= 1; _a(-1, "hidden div terkonfirmasi (breakdown minor)")
    S = _cap(S, 3)

    skor = T + M + V + S
    bias_skor = T + M
    label_bias = ("BULLISH" if bias_skor >= 5 else "Cenderung bullish" if bias_skor >= 2 else
                  "Netral" if bias_skor >= -1 else
                  "Cenderung bearish" if bias_skor >= -4 else "BEARISH")

    bull = bias_skor >= 2
    candle_bull = any(c["valid"] and c["arah"] == "bullish" for c in f["candles"])
    vol_rebound = "PENURUNAN RAWAN PALSU" in vol
    rebound = (bias_skor <= 1 and dekat_s and (r < 40 or (_ok(pb) and pb < 0.15))
               and (candle_bull or vol_rebound or f["fb_dn"])
               and not (regime == "TREND" and arah_di < 0))
    if bull and skor >= 9:   kategori = KAT_KUAT
    elif bull and skor >= 6: kategori = KAT_WATCH_BULL
    elif rebound:            kategori = KAT_REBOUND
    elif skor >= 4:          kategori = KAT_WATCH
    elif skor >= 0:          kategori = KAT_NETRAL
    else:                    kategori = KAT_AVOID

    catatan = []
    st = f.get("stop_target")
    rr = st["rr"] if st else None
    if kategori in KAT_LONG:
        if f["nilai_transaksi"] < MIN_LIKUIDITAS:
            kategori = KAT_ILLIQ; catatan.append("likuiditas rendah")
        else:
            if rr is None or rr < MIN_RR:
                kategori = KAT_WATCH
                catatan.append(f"R/R {rr:.2f} < {MIN_RR}" if rr is not None else "R/R n/a")
            elif f["regime_ihsg"] == "BEAR" and kategori in (KAT_KUAT, KAT_WATCH_BULL):
                kategori = KAT_WATCH; catatan.append("IHSG di bawah MA50 & MA200")

    det = {"T": T, "M": M, "V": V, "S": S, "bias": bias_skor, "label_bias": label_bias,
           "regime": regime, "catatan": catatan, "hidden_div": hd_dipakai, "tanda": tanda}
    return skor, alasan, kategori, det


def grade_kualitas(f, skor, kategori, det):
    if kategori in (KAT_AVOID, KAT_ILLIQ):
        return "-"
    st = f.get("stop_target") or {}
    rs20 = (f.get("rs") or {}).get("rs_20")
    vol = f["vol_verdict"] or ""
    js = f["jarak_support_pct"]
    cek = [
        det["bias"] >= 2,
        "Uptrend" in f["market_structure"]["struktur"],
        "KENAIKAN didukung volume" in vol or f["brk_valid_up"],
        40 <= f["rsi"] <= 75,
        (js is not None and js < 5) or bool(f["di_golden_zone"] and f["fib_naik"]),
        _ok(f["adx"]) and f["adx"] >= 22 and _ok(f["di_plus"]) and _ok(f["di_minus"]) and f["di_plus"] > f["di_minus"],
        _ok(rs20) and rs20 > 0,
        (st.get("rr") or 0) >= 2,
        _ok(f["ma200"]) and f["harga"] > f["ma200"],
        f["nilai_transaksi"] >= MIN_LIKUIDITAS,
    ]
    poin = sum(bool(x) for x in cek)
    if kategori == KAT_KUAT:       return "A" if poin >= 8 else "B"
    if kategori == KAT_WATCH_BULL: return "A" if poin >= 8 else ("B" if poin >= 6 else "C")
    if kategori == KAT_REBOUND:    return "B" if poin >= 5 else "C"
    return "B" if poin >= 7 else "C"


def narasi_singkat(m):
    harga, det = m["harga"], m["det"]
    nama_trend = {
        "UPTREND": "tren naik", "DOWNTREND": "tren turun", "SIDEWAYS": "bergerak menyamping",
        "Symmetrical Triangle": "menyempit (tunggu arah breakout)",
        "Ascending Triangle": "menyempit condong naik",
        "Descending Triangle": "menyempit condong turun",
        "Rising Wedge": "naik melebar (rawan koreksi)", "Melebar ke bawah": "turun melebar (volatil)",
    }
    t = next((v for k, v in nama_trend.items() if k in m["trend"]), m["trend"])
    b = [f"Harga {MU} {harga:,.0f} sedang {t}; regime {det['regime']}."]
    if m["support"]:
        b.append(f"Support {MU} {m['support']:,.0f} ({m['jarak_support_pct']:.1f}%).")
    if m["resistance"]:
        b.append(f"Resistance {MU} {m['resistance']:,.0f} ({m['jarak_resistance_pct']:.1f}%).")
    if _ok(m["adx"]): b.append(f"ADX {m['adx']:.0f}.")
    if m["atr_pct"] is not None: b.append(f"ATR {m['atr_pct']:.1f}%/hari.")
    k = m["kategori"]
    if k == KAT_KUAT:        b.append("Sinyal selaras lintas kelompok — kandidat kuat untuk diamati.")
    elif k == KAT_REBOUND:   b.append("Bias lemah tapi ada konfirmasi di dekat support → pantau reaksi.")
    elif k == KAT_WATCH_BULL: b.append("Bias positif — tunggu breakout resistance dengan volume.")
    elif k == KAT_AVOID:     b.append("Sinyal tidak mendukung — hindari dulu.")
    elif k == KAT_ILLIQ:     b.append("Likuiditas rendah — sulit dieksekusi.")
    else:                    b.append("Belum ada sinyal kuat.")
    if det["catatan"]: b.append("Filter: " + "; ".join(det["catatan"]) + ".")
    if "RAWAN PALSU" in (m["vol_verdict"] or ""): b.append("⚠ Volume rawan palsu.")
    ev = m.get("event") or {}
    if ev.get("exdiv") is not None: b.append(f"⚠ Ex-dividend ±{ev['exdiv']} hari lagi.")
    if ev.get("earn") is not None:  b.append(f"⚠ Laporan keuangan ±{ev['earn']} hari lagi.")
    return " ".join(b)


# =========================================================
# 10. PROYEKSI RISIKO (FHS, tanpa drift)
# =========================================================
def simulasi_fhs(df, hari=20, n_sim=None, lookback=250, lam=0.94, seed=42):
    n_sim = n_sim or N_SIM
    d = df.tail(lookback + 1)
    c, h, l = d["Close"].values, d["High"].values, d["Low"].values
    r = np.diff(np.log(c))
    L = len(r)
    var = np.empty(L); var[0] = np.var(r[:min(20, L)]) + 1e-10
    for t in range(1, L):
        var[t] = lam * var[t-1] + (1 - lam) * r[t-1] ** 2
    sig = np.sqrt(np.maximum(var, 1e-10))
    z = r / sig
    zc = z - z.mean()
    up = np.log(h[1:] / c[:-1]) / sig
    dn = np.log(l[1:] / c[:-1]) / sig

    rng = np.random.default_rng(seed)
    sig_s = np.full(n_sim, np.sqrt(lam * var[-1] + (1 - lam) * r[-1] ** 2))
    harga = np.full(n_sim, c[-1])
    cp, hp, lp = (np.empty((n_sim, hari)) for _ in range(3))
    for k in range(hari):
        idx = rng.integers(0, L, size=n_sim)
        ret = sig_s * zc[idx]
        u = np.maximum(sig_s * up[idx], ret)
        dd = np.minimum(sig_s * dn[idx], ret)
        hp[:, k], lp[:, k] = harga * np.exp(u), harga * np.exp(dd)
        harga = harga * np.exp(ret)
        cp[:, k] = harga
        sig_s = np.sqrt(lam * sig_s ** 2 + (1 - lam) * ret ** 2)
    return cp, hp, lp


# =========================================================
# 11. EVENT KORPORASI (opsional — lambat, 1 request per saham)
# =========================================================
def _ke_tgl(x):
    if isinstance(x, (list, tuple)):
        x = x[0] if x else None
    if x is None: return None
    try:
        return pd.Timestamp(x).normalize()
    except Exception:
        return None


def cek_event(ticker, horizon_hari=10):
    out = {"exdiv": None, "earn": None}
    try:
        cal = yf.Ticker(ticker).calendar
        if not isinstance(cal, dict): return out
        today = pd.Timestamp.now().normalize()
        for kunci, nama in (("Ex-Dividend Date", "exdiv"), ("Earnings Date", "earn")):
            tgl = _ke_tgl(cal.get(kunci))
            if tgl is not None:
                d = (tgl - today).days
                if 0 <= d <= horizon_hari: out[nama] = int(d)
    except Exception:
        pass
    return out


# =========================================================
# 12. ANALISA PER SAHAM + TABEL + TOP-N
# =========================================================
def analisa_lengkap(ticker, ihsg_close, period=PERIODE_DATA, hari=HARI_PROYEKSI,
                    seed=42, cek_ev=False):
    df = ambil_data(ticker, period)
    f = hitung_fitur(df, ihsg_close)
    if f is None: return None
    cp, hp, lp = simulasi_fhs(df, hari=hari, seed=seed)
    p10, p50, p90 = np.percentile(cp[:, -1], [10, 50, 90])
    s1, r1 = f["support"], f["resistance"]
    f.update({
        "ticker": ticker, "tanggal": df.index[-1].date(),
        "sektor": SEKTOR.get(ticker, "Lainnya"),
        "proyeksi_p10": float(p10), "proyeksi_p50": float(p50), "proyeksi_p90": float(p90),
        "prob_resistance": float((hp.max(axis=1) >= r1).mean() * 100) if r1 else None,
        "prob_support": float((lp.min(axis=1) <= s1).mean() * 100) if s1 else None,
        "event": cek_event(ticker) if cek_ev else {},
        "df_full": df, "df": df.tail(JENDELA_STRUKTUR), "jalur": cp,
    })
    return f


def evaluasi(m):
    skor, alasan, kategori, det = skor_rekomendasi(m)
    m.update(skor=skor, alasan=alasan, kategori=kategori, det=det,
             grade=grade_kualitas(m, skor, kategori, det))
    st = m.get("stop_target")
    m["posisi"] = hitung_posisi(m["harga"], st["sl"]) if (st and kategori in KAT_LONG) else None
    m["narasi"] = narasi_singkat(m)
    return m


def ring_hidden_div(m):
    hd = [d for d in (m.get("hidden_div") or []) if not d["invalid"]]
    if not hd: return ""
    out = []
    for arah in ("bullish", "bearish"):
        x = [d for d in hd if d["arah"] == arah]
        if x:
            konf = "✓" if any(d["konfirmasi"] for d in x) else "…"
            skor_ = " [skor]" if m["det"]["hidden_div"] == arah else ""
            out.append(f"{arah} ({'+'.join(d['indikator'] for d in x)}) {konf}{skor_}")
    return "; ".join(out)


GRADE_RANK = {"A": 0, "B": 1, "C": 2, "-": 3}


def buat_tabel(hasil):
    mom = pd.Series({m["ticker"]: m["ret_126"] for m in hasil}).rank(pct=True) * 100
    rows = []
    for m in hasil:
        st, ps, det = m.get("stop_target") or {}, m.get("posisi") or {}, m["det"]
        rs = m.get("rs") or {}
        ev = m.get("event") or {}
        ev_txt = ", ".join(x for x in (
            f"exdiv {ev['exdiv']}h" if ev.get("exdiv") is not None else "",
            f"laporan {ev['earn']}h" if ev.get("earn") is not None else "") if x)
        rows.append({
            "Ticker": m["ticker"], "Sektor": m["sektor"], "Harga": m["harga"],
            "Grade": m["grade"], "Kategori": m["kategori"], "Skor": m["skor"],
            "T": det["T"], "M": det["M"], "V": det["V"], "S": det["S"],
            "Regime": det["regime"], "Trend": m["trend"], "Bias": det["label_bias"],
            "Mingguan": m["mingguan"], "IHSG": m["regime_ihsg"],
            "RSI": round(m["rsi"], 1),
            "RVOL": round(m["vol_rvol"], 2) if _ok(m["vol_rvol"]) else None,
            "Volume": m["vol_verdict"],
            "ADX": round(m["adx"], 1) if _ok(m["adx"]) else None,
            "ATR%": round(m["atr_pct"], 2) if m["atr_pct"] is not None else None,
            "BB%": round(m["bb_pctb"], 2) if _ok(m["bb_pctb"]) else None,
            "vs MA200%": round((m["harga"] / m["ma200"] - 1) * 100, 1) if _ok(m["ma200"]) else None,
            "Mom6b%": round(m["ret_126"], 1) if _ok(m["ret_126"]) else None,
            "MomRank": round(mom[m["ticker"]], 0),
            "Jrk52wH%": round(m["jarak_52w"], 1),
            "RS20%": round(rs["rs_20"], 2) if _ok(rs.get("rs_20")) else None,
            "RS60%": round(rs["rs_60"], 2) if _ok(rs.get("rs_60")) else None,
            "Support": m["support"], "Resistance": m["resistance"],
            "JrkSup%": round(m["jarak_support_pct"], 2) if m["jarak_support_pct"] is not None else None,
            "JrkRes%": round(m["jarak_resistance_pct"], 2) if m["jarak_resistance_pct"] is not None else None,
            "GoldenZone": m["di_golden_zone"],
            "HiddenDiv": ring_hidden_div(m),
            "Likuid(Rp M)": round(m["nilai_transaksi"] / 1e9, 1),
            "SL": st.get("sl"), "TP1": st.get("tp1"), "TP2": st.get("tp2"),
            "R/R": round(st["rr"], 2) if st else None,
            "Lot": ps.get("lot"), "Nilai": ps.get("nilai"),
            "RugiJikaARB%Modal": round(ps["rugi_arb_pct_modal"], 2) if ps else None,
            "P10": round(m["proyeksi_p10"]), "P50": round(m["proyeksi_p50"]),
            "P90": round(m["proyeksi_p90"]),
            "Event": ev_txt,
            "Filter": "; ".join(det["catatan"]),
            "Alasan": ", ".join(m["alasan"]), "Narasi": m["narasi"],
        })
    d = pd.DataFrame(rows)
    d["_g"] = d["Grade"].map(GRADE_RANK)
    d = d.sort_values(["Skor", "_g", "MomRank"], ascending=[False, True, False])
    return d.drop(columns="_g").reset_index(drop=True)


def pilih_top(df_hasil, hasil, n=None, maks_per_sektor=None, maks_korelasi=None):
    # default dibaca saat dipanggil (bukan saat definisi) agar override config berlaku
    n = TOP_N if n is None else n
    maks_per_sektor = MAKS_PER_SEKTOR if maks_per_sektor is None else maks_per_sektor
    maks_korelasi = MAKS_KORELASI if maks_korelasi is None else maks_korelasi
    peta = {m["ticker"]: m for m in hasil}
    rets = pd.DataFrame({t: m["df_full"]["Close"].pct_change().tail(120) for t, m in peta.items()})
    corr = rets.corr()
    kandidat = df_hasil[df_hasil["Kategori"].isin(KAT_LONG + (KAT_WATCH,))]
    terpilih, sektor_ct, dilewati = [], {}, []
    for _, row in kandidat.iterrows():
        t, sek = row["Ticker"], row["Sektor"]
        if sektor_ct.get(sek, 0) >= maks_per_sektor:
            dilewati.append((t, f"sektor {sek} penuh")); continue
        kor = [c for c in terpilih if corr.loc[t, c] > maks_korelasi]
        if kor:
            dilewati.append((t, f"korelasi >{maks_korelasi} dgn {kor[0]}")); continue
        terpilih.append(t); sektor_ct[sek] = sektor_ct.get(sek, 0) + 1
        if len(terpilih) >= n: break
    return df_hasil[df_hasil["Ticker"].isin(terpilih)].set_index("Ticker").loc[terpilih].reset_index(), dilewati


# =========================================================
# 14. GRAFIK
# =========================================================
KAT_META = {
    KAT_KUAT:       ("Kandidat kuat", "#0b8a4e", "#d8f1e3", "#075c34",
                     "Tren, momentum, volume, dan lokasi harga selaras."),
    KAT_WATCH_BULL: ("Pantau, bias naik", "#4f9d6b", "#e6f3ea", "#2f6b47",
                     "Bias positif; tunggu pemicu (breakout atau pullback)."),
    KAT_REBOUND:    ("Potensi memantul", "#2456a6", "#dde8f7", "#1a3f7a",
                     "Bias lemah, tetapi ada konfirmasi di dekat support."),
    KAT_WATCH:      ("Pantau", "#c98a00", "#f8ecc9", "#7a5400",
                     "Belum cukup kuat, atau kena filter (mis. R/R rendah)."),
    KAT_NETRAL:     ("Netral", "#8b97a3", "#e7eaee", "#3d4853", "Belum ada sinyal yang jelas."),
    KAT_AVOID:      ("Hindari dulu", "#c62f3a", "#f6dcde", "#8a1f28", "Sinyal tidak mendukung."),
    KAT_ILLIQ:      ("Kurang likuid", "#5b6670", "#5b6670", "#ffffff",
                     "Nilai transaksi harian di bawah batas minimum."),
}
URUT_KAT = [KAT_KUAT, KAT_WATCH_BULL, KAT_REBOUND, KAT_WATCH, KAT_NETRAL, KAT_AVOID, KAT_ILLIQ]
GRUP = (("T", "Tren", 5), ("M", "Momentum", 4), ("V", "Volume", 2), ("S", "Lokasi / setup", 3))
REGIME_TXT = {"TREND": "Tren kuat", "RANGE": "Sideways", "MIX": "Campuran"}
MINGGUAN_TXT = {"UP": "naik", "DOWN": "turun", "NETRAL": "netral"}


def _meta(kat):
    return KAT_META.get(kat, KAT_META[KAT_NETRAL])


def gambar_ringkas(m, hari=HARI_PROYEKSI, mode=None):
    mode = mode or MODE_GRAFIK
    lengkap = (mode == "lengkap")
    view, full = m["df"], m["df_full"]
    ticker, n = m["ticker"], len(view)
    tail = lambda s: s.tail(n)
    long_ = m["kategori"] in KAT_LONG and bool(m.get("stop_target"))
    ma = lambda k: full["Close"].rolling(k).mean()

    apds = [mpf.make_addplot(tail(ma(50)), color="#2456a6", width=1.2),
            mpf.make_addplot(tail(ma(200)), color="#16222e", width=1.4)]
    if lengkap:
        _, bb_up, bb_lo, _, _ = hitung_bollinger(full["Close"])
        apds += [mpf.make_addplot(tail(ma(20)), color="orange", width=0.9),
                 mpf.make_addplot(tail(bb_up), color="gray", width=0.8, linestyle="--"),
                 mpf.make_addplot(tail(bb_lo), color="gray", width=0.8, linestyle="--"),
                 mpf.make_addplot(tail(hitung_vwma(full)), color="purple", width=1.0, linestyle="-.")]

    judul = (f"{ticker}  {NAMA.get(ticker, '')}   |   {_meta(m['kategori'])[0]} (skor {m['skor']:+d})"
             f"   |   {REGIME_TXT[m['det']['regime']]}")
    fig, axes = mpf.plot(view, type="candle", style="yahoo", volume=True, addplot=apds,
                         returnfig=True, figsize=(13, 8 if lengkap else 7.2),
                         ylabel=f"Harga ({MU})", ylabel_lower="Volume", tight_layout=True)
    ax = axes[0]
    ax.set_title(judul, loc="left", fontsize=13, fontweight="bold", pad=46)
    jml = 3 if lengkap else 2
    for lvl, _ in m["resistance_list"][:jml]:
        ax.axhline(lvl, color="#d62728", ls="--", lw=1)
        ax.text(0.995, lvl, f"R {MU} {lvl:,.0f}", transform=ax.get_yaxis_transform(),
                ha="right", va="bottom", fontsize=8, color="#d62728", fontweight="bold")
    for lvl, _ in m["support_list"][:jml]:
        ax.axhline(lvl, color="#2ca02c", ls="--", lw=1)
        ax.text(0.995, lvl, f"S {MU} {lvl:,.0f}", transform=ax.get_yaxis_transform(),
                ha="right", va="top", fontsize=8, color="#2ca02c", fontweight="bold")
    ada_tl = False
    for t, warna in [(m["res_line"], "#ff7f0e"), (m["sup_line"], "#1f77b4")]:
        if t is None: continue
        ada_tl = True
        xs = np.arange(t["i"], n + hari)
        ax.plot(xs, t["y0"] + t["slope"] * (xs - t["i"]), color=warna, lw=1.6)
    if m["fib"] is not None:
        f = m["fib"]; x0 = min(f["i_high"], f["i_low"])
        xs_f = np.arange(x0, n + hari)
        ax.fill_between(xs_f, f["level"][0.5], f["level"][0.618], color="#ffd700", alpha=0.20)
        if lengkap:
            ax.plot([f["i_low"], f["i_high"]], [f["L"], f["H"]], color="#8a6d00",
                    ls="--", lw=1, marker="o", ms=4, alpha=0.8)
            for r, y in f["level"].items():
                ax.plot(xs_f, [y] * len(xs_f), color="#b8860b", lw=0.9, alpha=0.7)
                ax.text(x0 - 1, y, f"Fib {r*100:.1f}%", ha="right", va="center",
                        fontsize=7, color="#8a6d00")
    for d in m.get("hidden_div") or []:
        if d["invalid"]: continue
        warna = "#00a000" if d["arah"] == "bullish" else "#c00000"
        ax.plot([d["i1"], d["i2"]], [d["harga1"], d["harga2"]], color=warna, lw=2.2,
                marker="^" if d["arah"] == "bullish" else "v", ms=7)
        ax.text(d["i2"], d["harga2"], f" Hidden div {d['indikator']}", fontsize=8, color=warna,
                fontweight="bold", va="top" if d["arah"] == "bullish" else "bottom")
    xk = np.arange(n - 1, n + hari)
    awal = float(view["Close"].iloc[-1])
    pct = {q: np.concatenate([[awal], np.percentile(m["jalur"], q, axis=0)]) for q in (10, 25, 50, 75, 90)}
    ax.fill_between(xk, pct[10], pct[90], color="#9467bd", alpha=0.14)
    if lengkap:
        ax.fill_between(xk, pct[25], pct[75], color="#9467bd", alpha=0.22)
        ax.plot(xk, pct[50], color="#9467bd", lw=1.8)
    st = m.get("stop_target")
    if long_:
        for key, warna, va, nm in (("sl", "red", "bottom", "Stop loss"), ("tp1", "green", "top", "Target 1")):
            ax.axhline(st[key], color=warna, lw=1.0, alpha=0.65)
            ax.text(0.005, st[key], f"{nm} {MU} {st[key]:,.0f}", transform=ax.get_yaxis_transform(),
                    ha="left", va=va, fontsize=8, color=warna)
    ax.axvline(n - 1, color="gray", ls=":", lw=0.8)
    ax.set_xlim(-1, n + hari + 1)

    h = [Line2D([0], [0], color="#2456a6", lw=1.4, label="MA50"),
         Line2D([0], [0], color="#16222e", lw=1.6, label="MA200"),
         Line2D([0], [0], color="#d62728", ls="--", label="Resistance"),
         Line2D([0], [0], color="#2ca02c", ls="--", label="Support")]
    if lengkap:
        h += [Line2D([0], [0], color="orange", lw=1, label="MA20"),
              Line2D([0], [0], color="gray", ls="--", lw=1, label="Bollinger"),
              Line2D([0], [0], color="purple", ls="-.", lw=1, label="VWMA20")]
    if ada_tl:
        h.append(Line2D([0], [0], color="#ff7f0e", lw=1.6, label="Garis tren"))
    if m["fib"] is not None:
        h.append(Patch(color="#ffd700", alpha=0.35, label="Golden zone 50–61,8%"))
    h.append(Patch(color="#9467bd", alpha=0.25, label="Rentang risiko 20 hari (80%, tanpa arah)"))
    if long_:
        h += [Line2D([0], [0], color="red", label="Stop loss"), Line2D([0], [0], color="green", label="Target 1")]
    ax.legend(handles=h, loc="lower left", bbox_to_anchor=(0, 1.0), fontsize=8.5, ncol=5,
              frameon=False, borderaxespad=0.3)
    return fig


def fig_ke_base64(fig, dpi=90):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def buat_gambar_top(peta, top, mode=None):
    out = {}
    for tk in top["Ticker"].tolist():
        try:
            out[tk] = fig_ke_base64(gambar_ringkas(peta[tk], mode=mode))
        except Exception as e:
            print(f"  Grafik {tk} gagal dibuat: {e}")
    return out


# =========================================================
# 14b. TAMPILAN HTML
# =========================================================
CSS_LAPORAN = r"""<style>
.scr{--ink:#16222e;--mute:#5d6b78;--line:#d5dbe1;--paper:#fff;--bg:#f3f5f7;--naik:#0b8a4e;--turun:#c62f3a;--amber:#b37a00;--biru:#2456a6;
font-family:"Inter","Segoe UI",system-ui,-apple-system,Roboto,sans-serif;font-size:14px;line-height:1.5;color:var(--ink);
background:var(--bg);padding:20px;max-width:1120px;margin:0 auto;font-variant-numeric:tabular-nums}
.scr *{box-sizing:border-box}
.scr h1{font-size:23px;margin:0 0 2px;font-weight:650;letter-spacing:-.01em}
.scr h2{font-size:17px;margin:30px 0 10px;font-weight:650}
.scr h3{font-size:13.5px;margin:0 0 6px;font-weight:650}
.scr p{margin:0 0 8px;max-width:72ch}
.scr .mute{color:var(--mute)}
.scr .kecil{font-size:12px}
.scr .papan{background:var(--paper);border:1px solid var(--line);padding:16px 18px;border-radius:6px}
.scr .sebaran{display:flex;height:36px;border-radius:4px;overflow:hidden;margin:12px 0 8px}
.scr .sebaran div{display:flex;align-items:center;justify-content:center;color:#fff;font-weight:650;min-width:0}
.scr .legenda{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12.5px;color:var(--mute)}
.scr .legenda i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.scr .pil{display:inline-block;padding:1px 9px;border-radius:10px;font-size:12.5px;font-weight:600;white-space:nowrap}
.scr .tag{display:inline-block;padding:0 7px;border:1px solid var(--line);border-radius:3px;font-size:12px;color:var(--mute);margin-right:4px;white-space:nowrap}
.scr .tw{overflow-x:auto;border:1px solid var(--line);border-radius:6px;background:var(--paper)}
.scr table{border-collapse:collapse;width:100%;min-width:820px}
.scr th{text-align:left;font-weight:600;font-size:12.5px;color:var(--mute);padding:9px 10px;border-bottom:1px solid var(--line);background:#fafbfc}
.scr td{padding:9px 10px;border-bottom:1px solid #eaeef1;vertical-align:middle}
.scr tr:last-child td{border-bottom:0}
.scr td.aks{border-left:4px solid var(--aks,#8b97a3)}
.scr .r{text-align:right}
.scr .tk{font-weight:650}
.scr .sub{display:block;font-size:12px;color:var(--mute);font-weight:400}
.scr .skor{display:inline-block;min-width:40px;text-align:center;padding:2px 6px;border-radius:4px;font-weight:700;color:#fff}
.scr .grp{display:inline-grid;grid-template-columns:auto auto;gap:2px 14px;font-size:12px}
.scr .gr{display:flex;align-items:center;gap:5px;white-space:nowrap}
.scr .gr b{min-width:24px;text-align:right;font-weight:600}
.scr .dv{position:relative;display:inline-block;width:54px;height:8px;background:#e5e9ed;border-radius:4px;vertical-align:middle}
.scr .dv i{position:absolute;top:0;height:100%;border-radius:4px}
.scr .dv:after{content:"";position:absolute;left:50%;top:-2px;width:1px;height:12px;background:#7b8895}
.scr details.kartu{background:var(--paper);border:1px solid var(--line);border-left:5px solid var(--aks,#8b97a3);border-radius:4px;margin:0 0 10px}
.scr details.kartu>summary{cursor:pointer;list-style:none;padding:11px 14px;display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px}
.scr details.kartu>summary::-webkit-details-marker{display:none}
.scr details.kartu>summary:before{content:"\25B8";color:var(--mute);width:10px}
.scr details.kartu[open]>summary:before{content:"\25BE"}
.scr details.kartu>summary:focus-visible{outline:2px solid var(--biru);outline-offset:-2px}
.scr .kb{padding:4px 16px 16px;border-top:1px solid #eaeef1}
.scr .kolom{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:18px 28px;margin-top:12px}
.scr ul.al{list-style:none;margin:0 0 10px;padding:0;font-size:13.5px}
.scr ul.al li{padding:2px 0 2px 20px;position:relative}
.scr ul.al li:before{position:absolute;left:0;font-weight:700}
.scr ul.al li.p:before{content:"+";color:var(--naik)}
.scr ul.al li.n:before{content:"\2212";color:var(--turun)}
.scr ul.al li.i:before{content:"\2022";color:var(--mute)}
.scr .gr4{display:grid;grid-template-columns:96px 54px 34px auto;align-items:center;gap:8px;font-size:13px;padding:1px 0}
.scr dl.kv{display:grid;grid-template-columns:auto 1fr;gap:3px 14px;margin:0;font-size:13.5px}
.scr dl.kv dt{color:var(--mute)}
.scr dl.kv dd{margin:0;text-align:right}
.scr .peringatan{margin-top:12px;padding:8px 12px;background:#fdf3d8;border-left:3px solid var(--amber);font-size:13px}
.scr .rg{position:relative;height:30px;margin:10px 0 2px}
.scr .rg .ln{position:absolute;top:14px;left:0;right:0;height:2px;background:#d5dbe1}
.scr .rg .rb{position:absolute;top:9px;height:12px;background:#d9cdf0;border-radius:2px}
.scr .rg .mk{position:absolute;top:3px;width:2px;height:24px;margin-left:-1px}
.scr .rgl{display:flex;justify-content:space-between;font-size:12px;color:var(--mute)}
.scr img.grafik{width:100%;height:auto;margin-top:14px;border:1px solid var(--line);border-radius:4px}
.scr details.lipat{margin:10px 0}
.scr details.lipat>summary{cursor:pointer;font-weight:600;padding:4px 0}
.scr details.lipat>summary:focus-visible{outline:2px solid var(--biru)}
.scr .panduan dt{font-weight:650;margin-top:10px}
.scr .panduan dd{margin:0;max-width:72ch}
</style>"""


def _e(x):
    return _html.escape(str(x), quote=True)


def _rp(x):
    return "–" if not _ok(x) else f"{MU} {x:,.0f}".replace(",", ".")


def _pct(x, d=1, tanda=True):
    if not _ok(x):
        return "–"
    return (f"{x:+.{d}f}" if tanda else f"{x:.{d}f}").replace(".", ",") + "%"


def _pil_kat(kat):
    lbl, _, bg, fg, _ = _meta(kat)
    return f'<span class="pil" style="background:{bg};color:{fg}">{_e(lbl)}</span>'


def _pil_skor(skor):
    warna = ("#0b8a4e" if skor >= 9 else "#4f9d6b" if skor >= 6 else "#b37a00" if skor >= 4
             else "#7b8895" if skor >= 0 else "#c62f3a")
    return f'<span class="skor" style="background:{warna}">{skor:+d}</span>'


def _bar_div(v, mx):
    w = min(abs(v) / mx, 1) * 50
    warna = "#0b8a4e" if v > 0 else ("#c62f3a" if v < 0 else "#8b97a3")
    kiri = 50 if v >= 0 else 50 - w
    return (f'<span class="dv" title="{v:+d} dari maks ±{mx}">'
            f'<i style="left:{kiri:.0f}%;width:{w:.0f}%;background:{warna}"></i></span>')


def _rincian_ringkas(det):
    sel = "".join(f'<span class="gr" title="{nm}: {det[k]:+d} dari ±{mx}">{k} {_bar_div(det[k], mx)}'
                  f'<b>{det[k]:+d}</b></span>' for k, nm, mx in GRUP)
    return f'<span class="grp">{sel}</span>'


def _rincian_panjang(det):
    return "".join(f'<div class="gr4"><span>{nm}</span>{_bar_div(det[k], mx)}<b>{det[k]:+d}</b>'
                   f'<span class="mute kecil">dari ±{mx}</span></div>' for k, nm, mx in GRUP)


def _arah_struktur(m):
    s = m["market_structure"]["struktur"]
    return "Naik" if "Uptrend" in s else ("Turun" if "Downtrend" in s else "Campuran")


def _peringatan(m):
    p = [f"Filter: {c}." for c in m["det"]["catatan"]]
    if m["rvol_outlier"]:
        p.append("Volume hari ini sangat tidak biasa (RVOL > 5×); bisa jadi transaksi nego, bukan tekanan pasar biasa.")
    if "RAWAN PALSU" in (m["vol_verdict"] or ""):
        p.append("Volume tidak mendukung arah harga (rawan palsu).")
    ev = m.get("event") or {}
    if ev.get("exdiv") is not None:
        p.append(f"Ex-dividend sekitar {ev['exdiv']} hari lagi; harga biasanya turun sebesar dividen.")
    if ev.get("earn") is not None:
        p.append(f"Laporan keuangan sekitar {ev['earn']} hari lagi; volatilitas bisa melonjak.")
    ps = m.get("posisi")
    if ps and ps["rugi_arb_pct_modal"] > 3 * RISIKO_PCT:
        p.append(f"Jika langsung turun ke batas ARB, rugi ±{ps['rugi_arb_pct_modal']:.1f}% modal, "
                 f"jauh di atas risiko yang direncanakan ({RISIKO_PCT:.0f}%). Stop loss bisa tidak terisi (gap).")
    return p


def _bar_rentang(m, long_):
    harga, p10, p90 = m["harga"], m["proyeksi_p10"], m["proyeksi_p90"]
    st = m.get("stop_target") if long_ else None
    pts = [harga, p10, p90] + ([st["sl"], st["tp1"]] if st else [])
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0
    pos = lambda v: (v - lo) / span * 100
    h = ('<div class="rg"><div class="ln"></div>'
         f'<div class="rb" style="left:{pos(p10):.1f}%;width:{max(pos(p90) - pos(p10), 0.5):.1f}%"></div>'
         f'<div class="mk" style="left:{pos(harga):.1f}%;background:#16222e" title="Harga {_rp(harga)}"></div>')
    if st:
        h += (f'<div class="mk" style="left:{pos(st["sl"]):.1f}%;background:#c62f3a" title="Stop loss {_rp(st["sl"])}"></div>'
              f'<div class="mk" style="left:{pos(st["tp1"]):.1f}%;background:#0b8a4e" title="Target 1 {_rp(st["tp1"])}"></div>')
    h += f'</div><div class="rgl"><span>{_rp(lo)}</span><span>{_rp(hi)}</span></div>'
    ket = "Hitam: harga. Ungu: rentang wajar 80% dalam 20 hari (simulasi tanpa arah)"
    if st:
        ket += ". Merah: stop loss. Hijau: target 1"
    return h + f'<div class="mute kecil">{ket}.</div>'


def html_kartu(m, momrank=None, gambar_b64=None, terbuka=False):
    det, st, ps = m["det"], m.get("stop_target"), m.get("posisi")
    lbl, aks, _, _, pen = _meta(m["kategori"])
    long_ = m["kategori"] in KAT_LONG and bool(st)
    harga, tk = m["harga"], m["ticker"]

    tanda = det.get("tanda") or [0] * len(m["alasan"])
    pasang = list(zip(m["alasan"], tanda))
    li = ("".join(f'<li class="p">{_e(a)}</li>' for a, t in pasang if t > 0)
          + "".join(f'<li class="n">{_e(a)}</li>' for a, t in pasang if t < 0)
          + "".join(f'<li class="i">{_e(a)}</li>' for a, t in pasang if t == 0))
    kolom1 = (f'<div><h3>Kenapa skornya {m["skor"]:+d}?</h3>'
              f'<ul class="al">{li or "<li class=i>Tidak ada sinyal yang menonjol</li>"}</ul>'
              f'{_rincian_panjang(det)}</div>')

    adx_txt = f"{REGIME_TXT[det['regime']]} (ADX {m['adx']:.0f})" if _ok(m["adx"]) else REGIME_TXT[det["regime"]]
    vol_txt = (m["vol_verdict"] or "n/a").split(" | ")[0]
    if _ok(m["vol_rvol"]):
        vol_txt += f" (RVOL {m['vol_rvol']:.1f}×)"
    kv = [("Tren (struktur harga)", _arah_struktur(m)), ("Kondisi saham", adx_txt),
          ("Tren mingguan", MINGGUAN_TXT.get(m["mingguan"], "n/a")), ("RSI", f"{m['rsi']:.0f}"),
          ("Posisi vs MA200", _pct((harga / m["ma200"] - 1) * 100) if _ok(m["ma200"]) else "–"),
          ("Volume", vol_txt)]
    if m["support"]:
        kv.append(("Support terdekat", f"{_rp(m['support'])} ({_pct(-m['jarak_support_pct'])})"))
        if m.get("prob_support") is not None:
            kv.append(("Peluang sentuh support, 20 hari", f"≈{m['prob_support']:.0f}%"))
    if m["resistance"]:
        kv.append(("Resistance terdekat", f"{_rp(m['resistance'])} ({_pct(m['jarak_resistance_pct'])})"))
        if m.get("prob_resistance") is not None:
            kv.append(("Peluang sentuh resistance, 20 hari", f"≈{m['prob_resistance']:.0f}%"))
    hd = ring_hidden_div(m)
    if hd:
        kv.append(("Hidden divergence", hd))
    if momrank is not None and _ok(momrank):
        kv.append(("Peringkat momentum 6 bulan", f"{momrank:.0f} dari 100"))
    kv.append(("Sektor", m["sektor"]))
    kolom2 = ('<div><h3>Kondisi dan level penting</h3><dl class="kv">'
              + "".join(f"<dt>{_e(a)}</dt><dd>{_e(b)}</dd>" for a, b in kv) + "</dl></div>")

    if long_:
        plan = [("Harga acuan (penutupan)", _rp(harga)),
                ("Stop loss", f"{_rp(st['sl'])} ({_pct(-st['sl_pct'])})"),
                ("Target 1", f"{_rp(st['tp1'])} ({_pct((st['tp1'] / harga - 1) * 100)})"),
                ("Target 2", f"{_rp(st['tp2'])} ({_pct((st['tp2'] / harga - 1) * 100)})"),
                ("Risk/Reward ke target 1", f"{st['rr']:.2f}"),
                ("Jarak stop loss", f"{st['jarak_sl_atr']:.1f}× ATR")]
        if ps:
            plan += [("Ukuran posisi", f"{ps['lot']} lot ≈ {_rp(ps['nilai'])}"),
                     ("Rugi jika kena stop loss", _rp(ps["risiko_rp"])),
                     ("Rugi jika langsung ARB", f"{_pct(-ps['rugi_arb_pct_modal'])} dari modal")]
        bagian_plan = '<dl class="kv">' + "".join(f"<dt>{_e(a)}</dt><dd>{_e(b)}</dd>" for a, b in plan) + "</dl>"
    else:
        bagian_plan = ('<p class="mute">Belum ada rencana trade: kategori ini bukan kandidat beli. '
                       'Rentang risiko di bawah tetap berlaku sebagai gambaran volatilitas.</p>')
    kolom3 = f'<div><h3>Rencana (bila ingin masuk)</h3>{bagian_plan}{_bar_rentang(m, long_)}</div>'

    warn = _peringatan(m)
    html_warn = ('<div class="peringatan">' + "".join(f"<div>{_e(w)}</div>" for w in warn) + "</div>") if warn else ""
    img = f'<img class="grafik" alt="Grafik {_e(tk)}" src="data:image/png;base64,{gambar_b64}">' if gambar_b64 else ""

    mutu = f'<span class="mute">Mutu sinyal {m["grade"]}</span>' if m["grade"] != "-" else ""
    ringkas = (f'<summary><span class="tk">{_e(tk)}</span><span class="mute">{_e(NAMA.get(tk, ""))}</span>'
               f'{_pil_kat(m["kategori"])}{_pil_skor(m["skor"])}{mutu}'
               f'<span>{_rp(harga)}</span><span class="mute kecil">data {m["tanggal"]}</span></summary>')
    return (f'<details class="kartu" style="--aks:{aks}"{" open" if terbuka else ""}>{ringkas}'
            f'<div class="kb"><p class="mute" style="margin-top:10px">{_e(pen)}</p>'
            f'<div class="kolom">{kolom1}{kolom2}{kolom3}</div>{html_warn}{img}'
            f'<p class="mute kecil" style="margin-top:12px">{_e(m["narasi"])}</p></div></details>')


def html_tabel(df_hasil, peta):
    th = ("<tr><th>Saham</th><th>Status</th><th>Skor</th><th>Rincian</th><th>Kondisi</th>"
          "<th class='r'>Harga</th><th class='r'>Ke support / resistance</th><th class='r'>R/R</th><th>Catatan</th></tr>")
    rows = []
    for _, r in df_hasil.iterrows():
        m = peta[r["Ticker"]]
        det, st = m["det"], m.get("stop_target")
        aks = _meta(m["kategori"])[1]
        kond_sub = f"{REGIME_TXT[det['regime']]}, mingguan {MINGGUAN_TXT.get(m['mingguan'], 'n/a')}"
        js, jr = m["jarak_support_pct"], m["jarak_resistance_pct"]
        rr = f"{st['rr']:.2f}" if (st and m["kategori"] in KAT_LONG) else "–"
        tags = ""
        if det["hidden_div"]:
            tags += (f'<span class="tag" title="Hidden divergence {det["hidden_div"]} masuk skor">'
                     f'Hidden div {"naik" if det["hidden_div"] == "bullish" else "turun"}</span>')
        w = _peringatan(m)
        if w:
            tags += f'<span class="tag" title="{_e(" ".join(w))}">{len(w)} peringatan</span>'
        rows.append(
            f'<tr><td class="aks tk" style="--aks:{aks}">{_e(m["ticker"].replace(".JK", ""))}'
            f'<span class="sub">{_e(NAMA.get(m["ticker"], ""))}</span></td>'
            f'<td>{_pil_kat(m["kategori"])}</td><td>{_pil_skor(m["skor"])}</td>'
            f'<td>{_rincian_ringkas(det)}</td>'
            f'<td><b>{_arah_struktur(m)}</b><span class="sub">{_e(kond_sub)}</span></td>'
            f'<td class="r">{_rp(m["harga"])}</td>'
            f'<td class="r">{_pct(-js) if js is not None else "–"} / {_pct(jr) if jr is not None else "–"}</td>'
            f'<td class="r">{rr}</td><td>{tags}</td></tr>')
    return f'<div class="tw"><table>{th}{"".join(rows)}</table></div>'


def html_header(hasil):
    tgl = max(m["tanggal"] for m in hasil)
    now = pd.Timestamp.now(tz="Asia/Jakarta").strftime("%d-%m-%Y %H:%M WIB")
    return (f'<h1>Screener IDX30</h1><p class="mute">Data penutupan terakhir {tgl}. Laporan dibuat {now}. '
            f'Alat penyaring teknikal, bukan rekomendasi beli atau jual.</p>')


def html_ringkasan(hasil, top, dilewati):
    n = len(hasil)
    cnt = {k: sum(1 for m in hasil if m["kategori"] == k) for k in URUT_KAT}
    seg = "".join(f'<div style="flex:{cnt[k]};background:{_meta(k)[1]}" title="{_meta(k)[0]}: {cnt[k]}">{cnt[k]}</div>'
                  for k in URUT_KAT if cnt[k])
    leg = "".join(f'<span><i style="background:{_meta(k)[1]}"></i>{_meta(k)[0]} {cnt[k]}</span>'
                  for k in URUT_KAT if cnt[k])
    reg = hasil[0]["regime_ihsg"]
    teks_reg = {"BULL": "IHSG di atas MA50 dan MA200: kondisi pasar mendukung.",
                "BEAR": "IHSG di bawah MA50 dan MA200: pasar lemah, kandidat beli otomatis diturunkan kelasnya.",
                "NETRAL": "IHSG campuran (di antara atau di sekitar MA50 dan MA200).",
                "NA": "Data IHSG tidak tersedia, filter pasar tidak aktif."}[reg]
    n_kand = sum(cnt[k] for k in KAT_LONG)
    if n_kand:
        pilihan = " ".join(f'<span class="tag" style="color:var(--ink)">{_e(t.replace(".JK", ""))}</span>'
                           for t in top["Ticker"])
        kalimat = (f"<p><b>{n_kand} dari {n} saham</b> masuk daftar kandidat. "
                   f"Pilihan utama setelah diversifikasi: {pilihan}</p>")
    else:
        kalimat = ("<p><b>Tidak ada saham yang lolos sebagai kandidat hari ini.</b> "
                   "Itu hasil yang sah; tidak perlu memaksa masuk pasar.</p>")
    lewat = ""
    if dilewati:
        lewat = ('<p class="mute kecil">Dilewati demi diversifikasi: '
                 + _e("; ".join(f"{t.replace('.JK', '')} ({a})" for t, a in dilewati)) + ".</p>")
    return (f'<div class="papan"><p style="margin-bottom:2px">{_e(teks_reg)}</p>{kalimat}'
            f'<div class="sebaran">{seg}</div><div class="legenda">{leg}</div>{lewat}</div>')


def html_panduan():
    status = "".join(f"<dt>{_pil_kat(k)}</dt><dd>{_e(_meta(k)[4])}</dd>" for k in URUT_KAT)
    return ('<details class="lipat panduan"><summary>Cara membaca laporan</summary><dl>'
            f'{status}'
            '<dt>Skor</dt><dd>Jumlah empat kelompok: Tren (maks ±5), Momentum (±4), Volume (±2), Lokasi/setup (±3), '
            'total maksimum ±14. Tiap kelompok dibatasi agar sinyal kembar tidak dihitung berulang. '
            'Kandidat kuat butuh skor 9 ke atas dengan bias naik; Pantau bias naik butuh 6 ke atas.</dd>'
            '<dt>Mutu sinyal A/B/C</dt><dd>Berapa dari 10 pemeriksaan kualitas yang lolos (tren, volume, RSI, lokasi, '
            'ADX, kekuatan relatif, R/R, MA200, likuiditas).</dd>'
            '<dt>Kondisi saham</dt><dd>Tren kuat bila ADX 25 ke atas, sideways bila di bawah 20. Aturan penilaian '
            'berbeda di tiap kondisi.</dd>'
            '<dt>Risk/Reward (R/R)</dt><dd>Jarak ke target 1 dibagi jarak ke stop loss. Kandidat beli dengan R/R di '
            f'bawah {MIN_RR} diturunkan ke "Pantau".</dd>'
            '<dt>Rentang wajar 20 hari</dt><dd>Hasil simulasi jalur harga tanpa kecenderungan naik atau turun. '
            'Ini gambaran risiko di sekitar harga sekarang, bukan prediksi.</dd>'
            '<dt>ARB</dt><dd>Batas penurunan harian. Jika harga jatuh ke batas ini, stop loss bisa tidak terisi di '
            'harga yang direncanakan; laporan menghitung rugi terburuknya.</dd>'
            '<dt>Hidden divergence</dt><dd>Harga membuat low yang lebih tinggi sementara indikator membuat low yang '
            'lebih rendah (kelanjutan tren naik). Hanya dihitung bila ada konteks tren dan lokasi pullback.</dd>'
            '</dl></details>')


def bangun_laporan(hasil, df_hasil, top, dilewati, gambar=None):
    gambar = gambar or {}
    peta = {m["ticker"]: m for m in hasil}
    mom = df_hasil.set_index("Ticker")["MomRank"]
    tk_top = top["Ticker"].tolist()
    kartu_top = "".join(html_kartu(peta[t], mom.get(t), gambar.get(t), terbuka=True) for t in tk_top)
    sisa = [t for t in df_hasil["Ticker"] if t not in tk_top]
    kartu_sisa = "".join(html_kartu(peta[t], mom.get(t)) for t in sisa)
    bagian = [CSS_LAPORAN, '<div class="scr">', html_header(hasil), html_ringkasan(hasil, top, dilewati),
              "<h2>Pilihan utama</h2>" + (kartu_top or '<p class="mute">Tidak ada.</p>'),
              "<h2>Semua saham</h2>", html_tabel(df_hasil, peta),
              '<h2>Detail saham lainnya</h2><p class="mute kecil">Klik baris untuk membuka.</p>' + kartu_sisa,
              html_panduan(), "</div>"]
    return "".join(bagian)


def scan_universe(tickers, ihsg_close, period=PERIODE_DATA, hari=HARI_PROYEKSI,
                  cek_ev=False, progress=None):
    """Prefetch batch lalu analisa berurutan. progress(i, n, kode) opsional."""
    kodes = [normalisasi_kode(t) for t in tickers]
    prefetch_data(kodes, period)
    hasil, gagal = [], []
    for i, kode in enumerate(kodes, 1):
        if progress: progress(i, len(kodes), kode)
        try:
            m = analisa_lengkap(kode, ihsg_close, period, hari, cek_ev=cek_ev)
            if m:
                evaluasi(m); hasil.append(m)
            else:
                gagal.append((kode, "data kurang"))
        except Exception as e:
            gagal.append((kode, str(e)))
    return hasil, gagal