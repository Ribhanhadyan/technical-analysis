# app.py — Streamlit wrapper untuk screener_core.py (v4.2 + realtime head-to-head, tanpa backtest)
# Install dependensi SEKALI lewat requirements.txt, bukan di dalam script:
#   streamlit, yfinance, mplfinance, pandas, numpy, matplotlib
import time
import pandas as pd
import streamlit as st

import screener_core as sc

st.set_page_config(page_title="Screener IDX30 v4.2", page_icon="📈", layout="wide")

# =========================================================
# SIDEBAR
# =========================================================
st.sidebar.title("⚙️ Pengaturan")

with st.sidebar.expander("Data & universe", expanded=True):
    PERIODE = st.selectbox("Periode", ["1y", "2y", "5y"], index=1)
    HARI = st.slider("Horizon proyeksi (hari)", 5, 60, 20)
    default_univ = "\n".join(sc.IDX30_DEFAULT)
    universe_txt = st.text_area("Universe (1 kode per baris)", default_univ, height=180)

with st.sidebar.expander("Filter & risiko", expanded=False):
    MIN_RR = st.number_input("Min R/R", 0.5, 5.0, 1.5, 0.1)
    MIN_LIK = st.number_input("Min likuiditas (Rp miliar)", 1.0, 500.0, 10.0, 1.0) * 1e9
    TOP_N = st.slider("Top N diversifikasi", 1, 10, 5)

with st.sidebar.expander("Opsional (lebih lambat)", expanded=False):
    CEK_EVENT = st.checkbox("Cek ex-dividend / laporan keuangan", value=False,
                            help="1 request tambahan per saham; data Yahoo untuk IDX sering kosong.")
    GRAFIK_TOP = st.checkbox("Sertakan grafik di kartu Pilihan utama", value=True)

with st.sidebar.expander("Realtime (head-to-head)", expanded=False):
    RT_INT = st.selectbox("Interval data intraday", ["1m", "2m", "5m", "15m"], index=2,
                          help="Yahoo menunda data IDX ±10 menit. Interval kecil = lebih halus, lebih berat.")
    AUTO_RT = st.checkbox("Auto-refresh realtime", value=False,
                          help="Memuat ulang data realtime berkala. Laporan lengkap ikut dimuat ulang, "
                               "jadi kartu yang sedang dibuka akan menutup kembali.")
    AUTO_DETIK = st.slider("Jeda auto-refresh (detik)", 30, 300, 60, 15)

# override konfigurasi core (dibaca saat fungsi dipanggil)
sc.PERIODE_DATA   = PERIODE
sc.HARI_PROYEKSI  = HARI
sc.MIN_RR         = MIN_RR
sc.MIN_LIKUIDITAS = MIN_LIK
sc.TOP_N          = TOP_N
sc.RT_INTERVAL    = RT_INT
sc.RT_CACHE_TTL   = max(10, min(45, AUTO_DETIK // 2))

tickers = list(dict.fromkeys(sc.normalisasi_kode(x.strip())
                             for x in universe_txt.splitlines() if x.strip()))


# =========================================================
# REALTIME: ambil data intraday & bandingkan dengan hasil screener
# =========================================================
def _wib_sekarang():
    return pd.Timestamp.now(tz="Asia/Jakarta").strftime("%H:%M:%S")


def muat_realtime(force=False):
    """Ambil data realtime semua saham hasil scan lalu hitung head-to-head vs screener."""
    hasil = st.session_state.get("hasil") or []
    if not hasil:
        return
    try:
        data, gagal = sc.ambil_realtime([m["ticker"] for m in hasil], force=force)
        st.session_state["h2h"] = sc.bandingkan_semua(hasil, data)
        st.session_state["rt_gagal"] = gagal
        st.session_state["rt_waktu"] = _wib_sekarang()
        st.session_state["rt_err"] = None
    except Exception as e:                       # jaringan/Yahoo bermasalah tidak boleh merusak halaman
        st.session_state["rt_err"] = f"{type(e).__name__}: {e}"


def _warna_hasil(v):
    if v == sc.VERDICT_META["SESUAI"][0]:     return "background-color:#d8f1e3;color:#075c34"
    if v == sc.VERDICT_META["CAMPURAN"][0]:   return "background-color:#f8ecc9;color:#7a5400"
    if v == sc.VERDICT_META["MENYIMPANG"][0]: return "background-color:#f6dcde;color:#8a1f28"
    return ""


def _warna_delta(v):
    if v is None or pd.isna(v): return ""
    return "color:#0b8a4e" if v > 0 else ("color:#c62f3a" if v < 0 else "")


# =========================================================
# HEADER
# =========================================================
st.title("📈 Screener IDX30 v4.2")
c1, c2 = st.columns([3, 1])
with c1:
    st.caption("Alat penyaring teknikal — bukan rekomendasi beli/jual.")
    st.caption("Created by: [Muhammad Ribhan Hadiyan](https://ribhanhadyan.vercel.app/)")
with c2:
    if st.button("🔄 Refresh data", use_container_width=True):
        sc.kosongkan_cache()
        for k in ("hasil", "ihsg", "laporan", "df_hasil", "top", "dilewati", "gambar",
                  "h2h", "rt_gagal", "rt_waktu", "rt_err"):
            st.session_state.pop(k, None)
        st.rerun()

tab_scan, tab_detail = st.tabs(["🔍 Screener", "📊 Detail per Saham"])


# =========================================================
# TAB 1: SCREENER
# =========================================================
def tampil_hasil():
    """Hasil scan + head-to-head realtime. Dijalankan sebagai fragment supaya auto-refresh
    hanya memuat ulang bagian ini, bukan seluruh halaman."""
    hasil = st.session_state.get("hasil")
    if not hasil:
        return
    df_hasil = st.session_state["df_hasil"]
    top = st.session_state["top"]
    peta = {m["ticker"]: m for m in hasil}

    # --- kontrol & status realtime (tetap di tab Screener, bukan tab baru) ---
    kol_a, kol_b = st.columns([1, 3])
    klik = kol_a.button("📡 Update realtime", use_container_width=True, key="btn_rt")
    if klik:
        with st.spinner("Mengambil data realtime…"):
            muat_realtime(force=True)
    elif AUTO_RT or "h2h" not in st.session_state:
        muat_realtime(force=False)

    h2h = st.session_state.get("h2h")
    sesi = sc.sesi_pasar()["status"]
    if st.session_state.get("rt_err"):
        kol_b.warning(f"Data realtime gagal dimuat: {st.session_state['rt_err']}")
    elif h2h:
        n = sc.hitung_verdict(h2h)
        kol_b.caption(
            f"Sesi pasar: **{sesi.lower()}** · update {st.session_state.get('rt_waktu', '–')} WIB · "
            f"✅ sesuai {n['SESUAI']} · 🟡 campuran {n['CAMPURAN']} · 🔴 menyimpang {n['MENYIMPANG']}"
            f" · belum dinilai {n['lain']}" + (" · auto-refresh aktif" if AUTO_RT else ""))
        gagal_rt = st.session_state.get("rt_gagal") or []
        if gagal_rt:
            kol_b.caption("Tanpa data realtime: " + "; ".join(f"{k.replace('.JK', '')} ({e})"
                                                              for k, e in gagal_rt))

    st.subheader("Pilihan utama")
    if len(top) == 0:
        st.info("Tidak ada kandidat yang lolos hari ini.")
    else:
        cols = st.columns(min(len(top), 5))
        for col, tk in zip(cols, top["Ticker"].tolist()):
            m = peta[tk]
            col.metric(tk.replace(".JK", ""), f"{sc.MU} {m['harga']:,.0f}",
                       f"skor {m['skor']:+d}")
            col.caption(f"{sc.KAT_META[m['kategori']][0]} · grade {m['grade']}")
            h = (h2h or {}).get(tk)
            if h and h.get("harga") is not None:
                chg = f" ({h['chg_pct']:+.2f}%)" if h.get("chg_pct") is not None else ""
                ket = sc.VERDICT_META[h["verdict"]][0] if h.get("verdict") else sc.RT_STATUS_TXT[h["status"]]
                col.caption(f"RT {sc.MU} {h['harga']:,.0f}{chg} · {ket}")

    if h2h:
        st.subheader("Head-to-head: screener vs realtime")
        st.caption("Kiri: hasil analisis teknikal (penutupan terakhir). Kanan: kondisi pasar yang sedang berjalan. "
                   "Kolom Hasil menilai apakah harga realtime sesuai ekspektasi screener "
                   "(arah, rentang wajar, support/resistance, SL/target, VWAP, volume).")
        tbl = sc.buat_tabel_h2h(df_hasil, h2h, peta)
        if not tbl.empty:
            fmt0, fmt2 = st.column_config.NumberColumn(format="%.0f"), st.column_config.NumberColumn(format="%.2f")
            cfg = {c: fmt0 for c in ("Close", "Harga RT", "Support", "Resistance", "SL", "TP1", "VWAP")}
            cfg.update({"Δ%": st.column_config.NumberColumn(format="%+.2f%%"), "RVOL RT": fmt2})
            try:
                tampil = tbl.style.map(_warna_hasil, subset=["Hasil"]).map(_warna_delta, subset=["Δ%"])
            except Exception:
                tampil = tbl
            st.dataframe(tampil, use_container_width=True, hide_index=True, column_config=cfg)

    st.subheader("Semua saham")
    st.dataframe(df_hasil, use_container_width=True, hide_index=True)

    st.subheader("Laporan lengkap")
    laporan = sc.bangun_laporan(hasil, df_hasil, top, st.session_state.get("dilewati", []),
                                st.session_state.get("gambar", {}), h2h=h2h)
    st.components.v1.html(laporan, height=1600, scrolling=True)


with tab_scan:
    if st.button("🚀 Jalankan Scan", type="primary", use_container_width=True):
        t0 = time.time()
        with st.spinner(f"Mengunduh data {len(tickers)} saham sekaligus…"):
            ihsg = sc.ambil_ihsg(PERIODE)
            sc.prefetch_data(tickers, PERIODE)          # 1 request batch
        reg = sc.regime_ihsg(ihsg)
        st.info(f"Regime IHSG: **{reg}** — menganalisa {len(tickers)} saham…")

        prog = st.progress(0.0, text="Memulai…")

        def _cb(i, n, kode):
            prog.progress(i / n, text=f"[{i}/{n}] {kode}")

        hasil, gagal = sc.scan_universe(tickers, ihsg, PERIODE, HARI,
                                        cek_ev=CEK_EVENT, progress=_cb)
        prog.empty()

        if hasil:
            # semua yang berat (tabel, top-N, grafik, HTML) dihitung SEKALI di sini,
            # bukan di setiap rerun Streamlit
            df_hasil = sc.buat_tabel(hasil)
            if sc.GAGAL_TABEL:
                st.warning("Dilewati saat membuat tabel: " +
                           "; ".join(f"{k} ({e})" for k, e in sc.GAGAL_TABEL))
                ok_tk = set(df_hasil["Ticker"]) if not df_hasil.empty else set()
                hasil = [m for m in hasil if m["ticker"] in ok_tk]
            if df_hasil.empty:
                st.error("Tidak ada saham yang berhasil diproses.")
                st.stop()
            top, dilewati = sc.pilih_top(df_hasil, hasil, n=TOP_N)
            peta = {m["ticker"]: m for m in hasil}
            gambar = sc.buat_gambar_top(peta, top) if GRAFIK_TOP else {}
            st.session_state["df_hasil"] = df_hasil
            st.session_state["top"] = top
            st.session_state["hasil"] = hasil
            st.session_state["ihsg"] = ihsg
            st.session_state["dilewati"] = dilewati
            st.session_state["gambar"] = gambar
            st.session_state.pop("h2h", None)
            with st.spinner("Mengambil data realtime…"):
                muat_realtime(force=True)
        if gagal:
            st.warning("Gagal: " + "; ".join(f"{k} ({e})" for k, e in gagal))
        st.caption(f"Selesai dalam {time.time() - t0:.1f} detik.")

    # auto-refresh hanya memuat ulang fragment ini; tanpa auto-refresh ia berjalan seperti biasa
    st.fragment(run_every=(AUTO_DETIK if AUTO_RT else None))(tampil_hasil)()

# =========================================================
# TAB 2: DETAIL SATU SAHAM
# =========================================================
with tab_detail:
    hasil_ss = st.session_state.get("hasil") or []
    default_tk = hasil_ss[0]["ticker"] if hasil_ss else "BBRI.JK"
    tk = st.text_input("Kode saham", default_tk)
    if st.button("Tampilkan"):
        try:
            ihsg = st.session_state.get("ihsg")
            if ihsg is None:
                ihsg = sc.ambil_ihsg(PERIODE)
            m = sc.analisa_lengkap(sc.normalisasi_kode(tk), ihsg, PERIODE, HARI,
                                   cek_ev=CEK_EVENT)
            if m:
                sc.evaluasi(m)
                # realtime untuk saham ini (gagal -> kartu tetap tampil tanpa panel realtime)
                h = None
                try:
                    rt_data, _ = sc.ambil_realtime([m["ticker"]], force=True)
                    h = sc.bandingkan_realtime(m, rt_data.get(m["ticker"]))
                except Exception as e:
                    st.warning(f"Data realtime tidak tersedia: {e}")
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Harga (penutupan)", f"{sc.MU} {m['harga']:,.0f}")
                col2.metric("Skor", f"{m['skor']:+d}")
                col3.metric("Kategori", sc.KAT_META[m["kategori"]][0])
                if h and h.get("harga") is not None:
                    col4.metric("Harga realtime", f"{sc.MU} {h['harga']:,.0f}",
                                f"{h['chg_pct']:+.2f}%" if h.get("chg_pct") is not None else None)
                else:
                    col4.metric("Harga realtime", "–")

                b64 = sc.fig_ke_base64(sc.gambar_ringkas(m, mode="lengkap"))
                body = sc.CSS_LAPORAN + '<div class="scr">' + \
                       sc.html_kartu(m, gambar_b64=b64, terbuka=True, h2h=h) + '</div>'
                st.components.v1.html(body, height=1500, scrolling=True)
            else:
                st.warning("Data tidak cukup (min. 120 bar).")
        except Exception as e:
            st.error(f"Gagal: {e}")
