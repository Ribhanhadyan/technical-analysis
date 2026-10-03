# app.py — Streamlit wrapper untuk screener_core.py (v4.2, tanpa backtest)
# Install dependensi SEKALI lewat requirements.txt, bukan di dalam script:
#   streamlit, yfinance, mplfinance, pandas, numpy, matplotlib
import time
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

# override konfigurasi core (dibaca saat fungsi dipanggil)
sc.PERIODE_DATA   = PERIODE
sc.HARI_PROYEKSI  = HARI
sc.MIN_RR         = MIN_RR
sc.MIN_LIKUIDITAS = MIN_LIK
sc.TOP_N          = TOP_N

tickers = list(dict.fromkeys(sc.normalisasi_kode(x.strip())
                             for x in universe_txt.splitlines() if x.strip()))

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
        for k in ("hasil", "ihsg", "laporan", "df_hasil", "top"):
            st.session_state.pop(k, None)
        st.rerun()

tab_scan, tab_detail = st.tabs(["🔍 Screener", "📊 Detail per Saham"])

# =========================================================
# TAB 1: SCREENER
# =========================================================
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
            top, dilewati = sc.pilih_top(df_hasil, hasil, n=TOP_N)
            peta = {m["ticker"]: m for m in hasil}
            gambar = sc.buat_gambar_top(peta, top) if GRAFIK_TOP else {}
            st.session_state["laporan"] = sc.bangun_laporan(hasil, df_hasil, top, dilewati, gambar)
            st.session_state["df_hasil"] = df_hasil
            st.session_state["top"] = top
            st.session_state["hasil"] = hasil
            st.session_state["ihsg"] = ihsg
        if gagal:
            st.warning("Gagal: " + "; ".join(f"{k} ({e})" for k, e in gagal))
        st.caption(f"Selesai dalam {time.time() - t0:.1f} detik.")

    if st.session_state.get("hasil"):
        hasil = st.session_state["hasil"]
        df_hasil = st.session_state["df_hasil"]
        top = st.session_state["top"]
        peta = {m["ticker"]: m for m in hasil}

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

        st.subheader("Semua saham")
        st.dataframe(df_hasil, use_container_width=True, hide_index=True)

        st.subheader("Laporan lengkap")
        st.components.v1.html(st.session_state["laporan"], height=1600, scrolling=True)

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
                col1, col2, col3 = st.columns(3)
                col1.metric("Harga", f"{sc.MU} {m['harga']:,.0f}")
                col2.metric("Skor", f"{m['skor']:+d}")
                col3.metric("Kategori", sc.KAT_META[m["kategori"]][0])

                b64 = sc.fig_ke_base64(sc.gambar_ringkas(m, mode="lengkap"))
                body = sc.CSS_LAPORAN + '<div class="scr">' + \
                       sc.html_kartu(m, gambar_b64=b64, terbuka=True) + '</div>'
                st.components.v1.html(body, height=1500, scrolling=True)
            else:
                st.warning("Data tidak cukup (min. 120 bar).")
        except Exception as e:
            st.error(f"Gagal: {e}")