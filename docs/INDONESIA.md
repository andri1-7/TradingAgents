# Saham Indonesia — IDX / BEI

Dukungan ini memakai Yahoo Finance melalui `yfinance`, bukan koneksi broker atau
feed resmi BEI. Tidak ada daftar seluruh emiten yang dibatasi dalam kode.

## Instalasi dan pemeriksaan data tanpa LLM

Dari root repositori, Python >= 3.11:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m tradingagents.indonesia --ticker BBCA --date 2026-10-26 --check-data
```

`--check-data` mengambil OHLCV saham dan IHSG (`^JKSE`) melalui jalur cache,
pemfilteran tanggal, dan pemeriksaan data basi yang sama dengan analisis.
Tidak membuat klien LLM, tidak membutuhkan API key LLM. JSON menampilkan tanggal
bar terakhir, jumlah bar, serta harga penutupan tersesuaikan dari Yahoo. Sumber
bisa berupa cache lokal; ini bukan jaminan harga real-time atau harga eksekusi.
Bar akhir pekan/libur bisa lebih awal dari tanggal permintaan. Candle hari ini
bisa belum final; gunakan tanggal sesi yang sudah selesai untuk evaluasi.
Tidak ada data menghasilkan `DATA_UNAVAILABLE` dan exit code 1, bukan harga rekaan.
Tanggal tidak valid/masa depan dan ticker bukan saham IDX ditolak (exit code 2).

## Analisis berbahasa Indonesia

```sh
# Konfigurasikan provider/model/API key sesuai README atau .env.example lebih dulu.
.venv/bin/python -m tradingagents.indonesia --ticker IDX:BBCA --date 2026-10-26
```

Tanpa `--check-data`, perintah menjalankan graph sebenarnya (market, news,
fundamentals), menyimpan laporan seperti graph upstream dan mencetak keputusan.
Ini dapat dikenai biaya oleh penyedia LLM. Pengujian fitur tidak memanggil LLM
berbayar. Model/provider tetap mengikuti pengaturan upstream/environment.
Analis social tidak dipilih karena cakupan feed sosial upstream bukan feed BEI.

Profil memakai bahasa Indonesian, mata uang kuotasi IDR, zona sesi Asia/Jakarta,
benchmark IHSG `^JKSE`, berita makro Indonesia/Bank Indonesia, dan vendor
`yfinance` untuk harga, indikator, fundamental dan berita. Instruksi pasar IDX
benar-benar masuk ke konteks instrumen yang dibaca agen, bukan hanya metadata
konfigurasi. Label rating mesin tetap berbahasa Inggris agar parser upstream bekerja.

Field harga/kuantitas numerik terstruktur wajib berupa **angka JSON**, memakai titik
(`.`) sebagai pemisah desimal, tanpa pemisah ribuan atau awalan `IDR`/`Rp`.
Contoh: `9000.5`, bukan `9.000,50` atau `"Rp 9.000,50"`. Laporan untuk manusia
boleh memakai format angka Indonesia, tetapi nilai terstruktur harus tetap kanonis.
Ini adalah instruksi pencegahan pada konteks IDX, **bukan perbaikan parser locale**:
parser numerik bersama masih berorientasi AS dan dapat membaca string `"9.000"`
sebagai `9.0` atau `"9.000,50"` sebagai `9.0005`. Jangan mengirim string angka
berformat lokal ke field numerik terstruktur; kepatuhan model tidak dijamin.

Untuk integrasi Python:

```python
from tradingagents.indonesia import build_indonesia_config
from tradingagents.graph.trading_graph import TradingAgentsGraph

config = build_indonesia_config()
graph = TradingAgentsGraph(selected_analysts=("market", "news", "fundamentals"), config=config)
state, rating = graph.propagate("BBCA.JK", "2026-10-26")
```

## Bentuk ticker dan contoh

Normalizer umum menerima `IDX:BBCA` dan `BEI:BBCA` menjadi `BBCA.JK`.
`BBCA.JK` tetap didukung. Simbol empat huruf tanpa penanda bursa **tidak** otomatis
dianggap Indonesia: `META`, `AAPL`, maupun `BBCA` tetap sama pada jalur umum.
Hanya entrypoint `tradingagents.indonesia` yang secara eksplisit memilih IDX dan
mengizinkan shorthand empat huruf seperti `BBCA`. Bentuk yang diterima bersifat
sintaksis, bukan validasi bahwa emiten masih tercatat; provider harus mengonfirmasi data.

Contoh pilihan, **bukan seluruh universe, rekomendasi, atau jaminan cakupan**:

| Yahoo ticker | Contoh emiten |
| --- | --- |
| BBCA.JK | Bank Central Asia |
| BBRI.JK | Bank Rakyat Indonesia |
| BMRI.JK | Bank Mandiri |
| TLKM.JK | Telkom Indonesia |
| ASII.JK | Astra International |

## Batasan penting

- SEC EDGAR AS tidak menjadi fallback untuk `.JK`, termasuk pada jalur umum.
  Profil Indonesia memakai Yahoo saja untuk fundamental.
- Transaksi insider Indonesia secara eksplisit mengembalikan data tidak tersedia,
  tanpa memanggil feed insider AS. Tidak tersedia **bukan** tidak ada transaksi.
  Periksa keterbukaan IDX/BEI, OJK, dan emiten untuk sumber primer.
- Guard point-in-time upstream tetap berlaku: fundamental Yahoo untuk tanggal
  historis dapat ditahan karena tidak memiliki vintage filing yang membuktikan
  kapan informasi diketahui. Fitur ini bukan backtest fundamental historis lengkap.
- Mata uang dan skala laporan keuangan harus dibaca dari sumber, bukan diasumsikan
  sama dengan IDR kuotasi. Berita, fundamental dan data emiten bisa tidak lengkap,
  terlambat, dibatasi rate limit, atau tidak tersedia; agen dilarang mengarangnya.
- `SELL` dibingkai sebagai pengurangan/penjualan posisi yang ada (long-only), bukan
  izin membuka short. Eksekusi, lot, biaya, pajak, likuiditas, suspensi, batas harga,
  kalender sesi dan kelayakan short tidak divalidasi. Tidak ada order yang dikirim.
- Tanggal bar mempertahankan tanggal lokal provider. Profil dan konteks menyebut
  Jakarta, tetapi kalender bursa resmi/session scheduling belum diimplementasikan.
  Logika historis upstream masih menggunakan tanggal hari ini pada host.
- Default pasar lain tidak berubah; map benchmark hanya ditambah `.JK -> ^JKSE`.

## Pengujian

```sh
.venv/bin/python -m pytest tests/test_indonesia.py tests/test_symbols.py tests/test_vendor_routing.py -q
.venv/bin/python -m pytest tests/ -q
```

Unit test tidak memakai jaringan. Analisis graph diuji dengan boundary LLM/graph
pengganti; data check diuji melalui boundary OHLCV, bukan respons API buatan yang
diklaim sebagai data live. Lihat [catatan REA](REA.md) untuk ruang lingkup
inspeksi bytecode terpisah dari validasi finansial.
