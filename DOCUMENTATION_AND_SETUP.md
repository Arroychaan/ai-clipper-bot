# 📘 DOKUMENTASI LENGKAP & PANDUAN SETUP `ai-clipper-bot`

Dokumentasi ini menjelaskan secara mendetail **apa saja yang sudah selesai dibuat**, **apa saja yang perlu Anda siapkan**, dan **panduan eksekusi step-by-step dari nol hingga bot berjalan 24/7 di server cloud VPS**.

---

## 📊 1. CHECKLIST STATUS PROYEK (SUDAH vs BELUM)

### ✅ SEJAUH INI YANG SUDAH DILAKUKAN (100% SELESAI OLEH AI)
1. **Arsitektur Kode & File Utama**:
   - `config.py`: Pengaturan variabel lingkungan, path absolut, spesifikasi video 9:16, dan mode *ramp-up schedule*.
   - `requirements.txt`: Seluruh dependensi produksi (`groq`, `pydub`, `yt-dlp`, `google-api-python-client`, `playwright`, `python-dotenv`).
   - `.env`: **10 API Key Groq Anda sudah diisikan dan terverifikasi 100% aktif**.
2. **Core AI & Pemrosesan Video**:
   - `core/db_manager.py`: Database SQLite (`bot_state.db`) untuk mencegah pemrosesan video ganda.
   - `core/groq_manager.py`: Modul Groq AI dengan rotasi 10 key otomatis, Speech-to-Text Whisper Large v3 (word timestamps), dan Llama 3.3 70B (deteksi hook & klip viral).
   - `core/fetcher.py`: Pengunduh audio 16kHz WAV & video 1080p MP4 via `yt-dlp`.
   - `core/audio_processor.py`: Detektor hening (`pydub.silence`) untuk kalibrasi pemotongan kalimat utuh + pembuat file subtitle animasi `.srt`.
   - `core/ffmpeg_renderer.py`: Renderer video vertical 9:16 (background blur + foreground overlay + burned-in subtitles) berbasis 1-pass CPU FFmpeg.
3. **Multi-Platform Uploader & Scheduler**:
   - `uploader/youtube_uploader.py`: Module upload resmi ke YouTube Shorts via Google OAuth2.
   - `uploader/tiktok_uploader.py`: Module upload otomatis ke TikTok Creator Center via Playwright Headless Chromium.
   - `main.py`: Infinite loop event manager 24/7 dengan fitur *atomic cleanup* `try...finally` (menghapus sampah `.mp4`, `.wav`, `.srt` dari memori secara pasti).
   - `ai-clipper.service`: Service systemd untuk autostart 24/7 di Ubuntu 24.04 / Oracle Cloud VPS.

---

### ⏳ YANG BELUM / PERLU ANDA SIAPKAN (ACTION ITEMS ANDA)
1. **Instalasi FFmpeg** di komputer Anda (atau di VPS).
2. **Pengisian Kredensial Upload (Opsional untuk Auto-Publish)**:
   - File OAuth2 YouTube: `config/tokens/client_secrets.json`
   - File Cookie TikTok: `config/tokens/tiktok_cookies.json`
3. **Menjalankan Script** (baik secara lokal di PC atau di server VPS 24/7).

---

## 🛠️ 2. CARA SETUP LENGKAP STEP-BY-STEP

---

### STEP 1: Instalasi FFmpeg di Komputer/Server

Bot membutuhkan program **FFmpeg** untuk memotong & merender video vertical.

#### A. Jika Anda Menggunakan Windows (PC Lokal)
1. Unduh FFmpeg buatan Bytedance/Gytt atau dari [ffmpeg.org/download.html](https://ffmpeg.org/download.html).
2. Extract file zip (misal ke `C:\ffmpeg`).
3. Tambahkan `C:\ffmpeg\bin` ke **System Environment Variables (PATH)** Windows.
4. Buka Terminal/CMD dan ketik: `ffmpeg -version` (pastikan perintah dikenali).

#### B. Jika Anda Menggunakan Server Linux (Ubuntu 24.04 / Oracle Cloud VPS)
Jalankan perintah ini di terminal server VPS:
```bash
sudo apt update && sudo apt install -y ffmpeg python3-pip python3-venv git
```

---

### STEP 2: Mengaktifkan Environment & Install Dependensi Python

Buka terminal pada folder proyek `ai-clipper-bot`:

#### Di Windows:
```powershell
cd "d:\Achmad Roychan\Proyek\New folder\generate-conten\ai-clipper-bot"

# 1. Buat Virtual Environment Python
python -m venv venv

# 2. Aktifkan Virtual Environment
.\venv\Scripts\activate

# 3. Install seluruh library Python
pip install -r requirements.txt

# 4. Install browser Chromium Playwright
playwright install chromium
```

#### Di Linux Ubuntu VPS:
```bash
cd /home/ubuntu/ai-clipper-bot

# 1. Buat & Aktifkan Virtual Environment
python3 -m venv venv
source venv/bin/activate

# 2. Install library Python
pip install --upgrade pip
pip install -r requirements.txt

# 3. Install Playwright Chromium & OS Dependencies
playwright install chromium
playwright install-deps chromium
```

---

### STEP 3: Konfigurasi Target Channel YouTube (`.env`)

Buka file **[.env](file:///d:/Achmad%20Roychan/Proyek/New%20folder/generate-conten/ai-clipper-bot/.env)** di editor. Pasikan isinya sesuai dengan channel target yang ingin Anda klip secara otomatis:

```env
# 10 Groq API Key Anda (Sudah terisi & terverifikasi)
GROQ_KEY_1=gsk_your_key_1_here
...
GROQ_KEY_10=gsk_your_key_10_here

# Ganti URL ini dengan Channel YouTube target Anda (misal podcast/seminar)
SOURCE_FEED_URL=https://www.youtube.com/@HubermanLab/videos
MAX_FEED_ITEMS=5

# Mode Ramp-Up (true = 3 video/hari interval 8 jam; false = 10 video/hari interval 2.4 jam)
RAMPUP_MODE=true
```

---

### STEP 4: Setup Kredensial Upload Auto-Publish (Opsional)

> **Catatan**: Jika langkah ini dilewati, bot tetap memproses video, transkrip, subtitle, dan merender video vertical di folder `temp/`, namun langkah upload otomatis ke platform akan dilewati secara aman.

#### A. Setup YouTube Shorts (`client_secrets.json`)
1. Masuk ke [Google Cloud Console](https://console.cloud.google.com/).
2. Buat Project Baru (misal: `AIClipperBot`).
3. Masuk ke **APIs & Services > Library**, cari **YouTube Data API v3**, lalu klik **Enable**.
4. Masuk ke **APIs & Services > Credentials** > Klik **Create Credentials** > **OAuth client ID**.
5. Pilih type **Desktop App**, lalu klik **Create**.
6. Klik ikon **Download JSON**.
7. Rename file tersebut menjadi `client_secrets.json` dan simpan ke:
   ```
   ai-clipper-bot/config/tokens/client_secrets.json
   ```

#### B. Setup TikTok Native (`tiktok_cookies.json`)
1. Buka browser Chrome dan pastikan Anda sudah login ke akun TikTok Anda.
2. Install ekstensi Chrome **Get cookies.txt LOCALLY** (atau ekstensi Cookie Editor).
3. Buka situs `tiktok.com`, buka ekstensi tersebut, lalu klik **Export Cookies as JSON**.
4. Simpan file JSON tersebut ke:
   ```
   ai-clipper-bot/config/tokens/tiktok_cookies.json
   ```

---

## 🚀 3. CARA MENJALANKAN BOT

### Opsi 1: Menjalankan Secara Lokal di PC Anda
Untuk menguji coba atau menjalankan bot di PC pribadi:

```powershell
# 1. Pastikan venv aktif
.\venv\Scripts\activate

# 2. Jalankan main.py
python main.py
```
Bot akan langsung membaca video terbaru dari channel target, melakukan transkripsi AI, merender video 9:16 dengan subtitle animasi, mengunggahnya, dan melakukan pembersihan sampah otomatis.

---

### Opsi 2: Deployment 24/7 Nonstop di Server Cloud Linux (VPS)

Agar bot bekerja 24 jam sehari secara otomatis tanpa perlu menyalakan PC lokal:

1. Salin seluruh folder `ai-clipper-bot` ke server VPS Anda (misal di `/home/ubuntu/ai-clipper-bot`).
2. Masuk ke VPS dan daftarkan service autostart systemd:
   ```bash
   # 1. Salin service file
   sudo cp ai-clipper.service /etc/systemd/system/

   # 2. Reload systemd & aktifkan autostart saat server reboot
   sudo systemctl daemon-reload
   sudo systemctl enable ai-clipper.service

   # 3. Jalankan service sekarang
   sudo systemctl start ai-clipper.service
   ```

3. **Cara Memantau Log Live Bot di VPS**:
   ```bash
   # Melihat aktivitas bot secara realtime:
   sudo journalctl -u ai-clipper.service -f
   
   # Atau cek file log lokal:
   tail -f logs/system.log
   ```

4. **Cara Menghentikan / Restart Bot di VPS**:
   - Restart: `sudo systemctl restart ai-clipper.service`
   - Stop: `sudo systemctl stop ai-clipper.service`
