# Radar Berita Dunia

Dashboard berita luar negeri yang gratis dan bisa dibuka siapa saja dari HP atau laptop. Datanya **hanya diperbarui saat Anda memicunya**, tidak ada jadwal otomatis.

**Menu**
- **Berita**: daftar berita 48 jam terakhir, lengkap dengan sumber dan topiknya. Ada filter 3 topik utama dengan subtopiknya:
  - Saham & Ekonomi: Saham AS, Saham Indonesia, Komoditas, Makro
  - Cuaca, Bencana & Wabah: Cuaca & Iklim, Bencana, Wabah & Penyakit
  - Teknologi: AI, Energi, Chip & Hardware, Antariksa, Siber
  
  Berita juga bisa disaring per jenis sumber atau hanya yang terkonfirmasi 2+ media, dan dicari lewat kotak pencarian.
- **Sumber Data**: total data yang diambil per sumber dan per jenis sumber (kumulatif sejak awal), status tiap sumber, jumlah berita per topik, dan riwayat item baru per update.

**Sumber (semua gratis, tanpa API key)**: RSS BBC, Al Jazeera, The Guardian, DW, NPR, CNBC, CNBC Indonesia, TechCrunch, The Verge, dan Ars Technica. Ditambah WHO dan GDACS, Google News (Reuters, AP, IHSG, Wall Street, wabah, AI, energi), GDELT, serta Reddit (r/worldnews, r/Economics, r/technology, r/artificial).

## Cara memasang (sekali saja, ±10 menit)

1. Buat akun di github.com (gratis), lalu buat repository baru dengan visibilitas **Public**, misalnya `radar-berita-dunia`. Pages dan Actions gratis untuk repo publik.
2. Upload semua isi folder ini ke repo: tombol **Add file → Upload files**, lalu seret semua file dan folder. Folder `.github` ikut tersembunyi di Mac, jadi tekan `Cmd+Shift+.` di Finder supaya terlihat.
3. Buka **Settings → Pages**, lalu pada **Source** pilih **GitHub Actions**.
4. Buka tab **Actions**, pilih **Update berita**, lalu klik **Run workflow**. Tunggu 1–2 menit sampai centangnya hijau.
5. Dashboard aktif di `https://NAMA-AKUN.github.io/radar-berita-dunia/`. Bagikan link ini ke siapa saja.

## Cara update
Ada dua pilihan, terserah Anda:
- **Tanpa token Claude**: buka tab Actions → Update berita → Run workflow. Bisa juga dari aplikasi GitHub di HP.
- **Lewat prompt ke Claude**, misalnya "update dashboard berita". Claude menjalankan workflow yang sama di GitHub. Token yang terpakai hanya untuk perintah itu, karena pengambilan berita tetap dikerjakan server GitHub.

Satu kali update makan waktu sekitar 1–2 menit, lalu halaman menampilkan data terbaru.

## Catatan
- Reddit kadang memblokir server GitHub. Jika itu terjadi, sumber Reddit tampil "gagal" di menu Sumber Data dan dashboard memakai data Reddit terakhir yang berhasil. Sumber lain tidak terpengaruh.
- Tanpa jadwal otomatis, menu Sumber Data menghitung total kumulatif dari update-update yang Anda jalankan saja.
- Topik ditentukan dari kata kunci, jadi sesekali bisa meleset. Daftar kata kuncinya ada di `scripts/fetch_news.py` (bagian `TAGS`) dan bisa ditambah.
- Menambah sumber: tambahkan satu baris di daftar `FEEDS` di `scripts/fetch_news.py`.
