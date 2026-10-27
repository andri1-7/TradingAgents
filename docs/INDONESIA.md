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

## Keputusan final TypeSafe Jev (opsional)

```sh
# Set TYPESAFE_API_KEY securely in the environment; never put a key in a report.
.venv/bin/python -m tradingagents.indonesia --ticker BBCA --date 2026-10-26 --jev-decision
```

`--jev-decision` menjalankan analisis utama dahulu, lalu meminta keputusan final
terstruktur `BUY` / `HOLD` / `SELL` melalui client `system_one` yang sudah ada.
Ini bukan sekadar screening sosial dan **bukan pengganti chat model** untuk graph.
Tanpa flag ini tidak ada permintaan Jev final; `--check-data` selalu mengabaikan
flag ini, tanpa Jev maupun graph LLM. API key kosong/hanya spasi ditolak sebelum
membuat graph berbayar. Key tidak kosong tetap dapat ditolak server; izin/billing
harus diverifikasi terpisah sebelum menjalankan analisis berbayar.

Default endpoint: `https://api.typesafe.ai/v1/systemone`, model `jev-latest`.
Client bersama menghormati `TYPESAFE_BASE_URL` dan `TYPESAFE_DEFAULT_MODEL`.
Ia mengirim pertanyaan `choice` dengan criteria mapping tiga label tersebut,
memakai timeout dan retry terbatas upstream. Hanya ticker/as-of yang persis
setelah normalisasi CLI dan whitelist string laporan dikirim: `market_report`,
`news_report`, `fundamentals_report`, `sentiment_report`, `investment_plan`,
`trader_investment_plan`, `final_trade_decision`. Setiap laporan dibatasi 16.000
karakter; laporan akhir wajib tersedia. Messages, credentials, object arbitrer,
dan state graph lain tidak dikirim. Hindari memasukkan rahasia ke teks laporan.

Hasil harus memiliki choice tepat salah satu dari tiga label, probabilities dengan
key tepat `BUY`, `HOLD`, `SELL`, angka finite 0..1 dan jumlah 1 (toleransi absolut
1e-6), serta confidence finite 0..1. Boolean/string numerik ditolak. Confidence dan
probabilities ini adalah penilaian klasifikasi model, **bukan peluang profit**,
bukan bukti kalibrasi pada IDX, dan bukan hasil backtest. `SELL` hanya berarti
mengurangi/keluar dari posisi long yang sudah ada, bukan membuka short. Tidak ada
harga, return, target eksekusi, atau hasil investasi yang dibuat oleh fitur ini.

Output melabeli `Original model report/rating` terpisah dari `Jev final decision`.
Artifact baru ditulis di
`<results_dir>/<ticker>/<as_of>/jev_decision_<unique-id>.json` dengan hasil Jev,
ticker/as-of, original model report/rating dan `requested_model`. Client bersama
hanya mengembalikan answers; `resolved_model` disimpan `null`, tidak mengklaim
alias seperti `jev-latest` sebagai versi model server yang persis. Artifact ini
**tidak** menimpa keputusan graph, memory/reflection atau hasil backtest upstream;
semua itu tetap menggunakan model utama. Tidak ada order yang dikirim.

Kegagalan API, respons tidak valid, atau penulisan artifact menghasilkan
`JEV_UNAVAILABLE` dan exit code 1 tanpa menerbitkan keputusan Jev (tidak ada
fallback HOLD rekaan). Laporan utama yang sudah selesai tetap dilabeli sebagai
hasil model utama. Unit/integration test memakai graph/client/HTTP boundary
mocked, tidak memanggil model berbayar dan tidak mengklaim validasi API live.

## Registry emiten BEI

Registry bawaan memuat **962 kode unik** dari snapshot endpoint saham BEI, termasuk papan pemantauan khusus. Semua baris snapshot didaftarkan, bukan hanya lima contoh. Ini **belum terbukti seluruh emiten terkini**: ANTARA mengutip 963 perusahaan per 23 Oktober 2026, sedangkan sumber yang dapat diambil mengembalikan 962. Selisih belum terjelaskan; tidak ada kode yang dikarang. Dataset-as-of tidak diketahui; timestamp pengambilan bukan tanggal berlaku data. Lihat [provenance](IDX-DATA-SOURCES.md).

```sh
python -m tradingagents.idx_registry info
python -m tradingagents.idx_registry list --format csv
python -m tradingagents.idx_registry list --format tickers
python -m tradingagents.idx_registry list --search bank --format json
```

Daftar tidak dipotong top-N. Registrasi tidak membuktikan masih diperdagangkan, cakupan Yahoo, atau mengaktifkan scanner/analisis berbayar. Format JSON menyertakan metadata jumlah universe dan matched_count setelah filter.

Untuk memperbarui dari file JSON respons IDX lengkap (Code/Name atau KodeEmiten/NamaEmiten):

```sh
python -m tradingagents.idx_registry import --input /path/idx-response.json --output /path/registry.json --source-url 'https://www.idx.co.id/primary/StockData/GetSecuritiesStock'
python -m tradingagents.idx_registry --registry /path/registry.json list --format tickers
```

Import menolak jumlah respons tidak cocok, ticker tidak valid, dan duplikat; penulisan atomik menjaga snapshot lama jika gagal. Tidak melakukan scraping atau pemanggilan API otomatis. Impor file lokal tidak menyertifikasi asal atau kesegaran data, sehingga kelengkapan tetap berlabel unverified.

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
