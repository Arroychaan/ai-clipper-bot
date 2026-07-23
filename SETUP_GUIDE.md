# 🚀 Panduan Lengkap Setup & Deployment 24/7 `ai-clipper-bot`

Dokumentasi ini berisi panduan instalasi, konfigurasi kredensial, pengujian lokal, dan deployment 24/7 nonstop di server Linux VPS (Oracle Cloud / Ubuntu 24.04).

---

## 📋 DAFTAR ISI
1. [Kebutuhan Sistem (Prerequisites)](#1-kebutuhan-sistem-prerequisites)
2. [Instalasi Environment & Dependensi](#2-instalasi-environment--dependensi)
3. [Konfigurasi File Environment (.env)](#3-konfigurasi-file-environment-env)
4. [Setup Kredensial Upload YouTube Shorts](#4-setup-kredensial-upload-youtube-shorts)
5. [Setup Cookie Upload TikTok Native](#5-setup-cookie-upload-tiktok-native)
6. [Pengujian & Eksekusi Lokal](#6-pengujian--eksekusi-lokal)
7. [Deployment 24/7 di Server Linux (Ubuntu VPS)](#7-deployment-247-di-server-linux-ubuntu-vps)
8. [Monitoring Log & Pemeliharaan](#8-monitoring-log--pemeliharaan)

---

## 1. Kebutuhan Sistem (Prerequisites)

- **Python**: v3.12+ (disarankan v3.12)
- **FFmpeg**: Wajib terinstall di sistem host OS (untuk rendering video 9:16 vertical & audio processing)
- **Server VPS** (Opsional untuk 24/7 nonstop): Ubuntu 24.04 / Oracle Cloud VPS (Bebas GPU / 100% CPU-based)
- **Kredensial API**:
  - Minimal 1-10 API Key Groq gratis ([console.groq.com](https://console.groq.com))
  - Account YouTube & TikTok aktif

---

## 2. Instalasi Environment & Dependensi

### A. Di Server Linux (Ubuntu 24.04 / Oracle Cloud)

```bash
# 1. Update paket & install dependensi sistem (FFmpeg & Python)
sudo apt update && sudo apt install -y python3-pip python3-venv ffmpeg git

# 2. Masuk ke folder bot
cd /home/ubuntu/ai-clipper-bot

# 3. Buat & aktifkan virtual environment Python
python3 -m venv venv
source venv/bin/activate

# 4. Install library Python
pip install --upgrade pip
pip install -r requirements.txt

# 5. Install headless Chromium browser & OS dependencies untuk Playwright (Wajib)
playwright install chromium
playwright install-deps chromium
```

### B. Di Komputer Lokal (Windows)

```powershell
# 1. Pastikan FFmpeg sudah terinstall & masuk di PATH Windows
ffmpeg -version

# 2. Masuk ke folder bot
cd "d:\Achmad Roychan\Proyek\New folder\generate-conten\ai-clipper-bot"

# 3. Buat & aktifkan virtual environment
python -m venv venv
.\venv\Scripts\activate

# 4. Install library Python & Playwright Chromium
pip install -r requirements.txt
playwright install chromium
```

---

## 3. Konfigurasi File Environment (`.env`)

File `.env` sudah dibuat otomatis di direktori utama `ai-clipper-bot/.env`. Isi file meliputi 10 API Key Groq dan parameter kerja:

```env
# Groq API Keys (Rotasi Otomatis 10 Keys)
GROQ_KEY_1=gsk_your_key_1_here
GROQ_KEY_2=gsk_your_key_2_here
GROQ_KEY_3=gsk_your_key_3_here
GROQ_KEY_4=gsk_your_key_4_here
GROQ_KEY_5=gsk_your_key_5_here
GROQ_KEY_6=gsk_your_key_6_here
GROQ_KEY_7=gsk_your_key_7_here
GROQ_KEY_8=gsk_your_key_8_here
GROQ_KEY_9=gsk_your_key_9_here
GROQ_KEY_10=gsk_your_key_10_here

# Sumber Channel YouTube Feed Target
SOURCE_FEED_URL=https://www.youtube.com/@HubermanLab/videos
MAX_FEED_ITEMS=5

# Mode Ramp-Up Jeda Upload
# RAMPUP_MODE=true: 3 video/hari (~8 jam interval) untuk akun baru agar aman dari anti-spam
# RAMPUP_MODE=false: 10 video/hari (~2.4 jam interval) untuk akun aktif
RAMPUP_MODE=true
RAMPUP_INTERVAL_SEC=28800
STANDARD_INTERVAL_SEC=8640
RETRY_DELAY_SEC=60
```

---

## 4. Setup Kredensial Upload YouTube Shorts

Untuk mengaktifkan fitur upload otomatis ke YouTube Shorts via YouTube Data API v3:

1. Buka [Google Cloud Console](https://console.cloud.google.com/).
2. Buat proyek baru (contoh: `AIClipperBot`).
3. Buka menu **APIs & Services > Library**, cari **YouTube Data API v3**, lalu klik **Enable**.
4. Buka **APIs & Services > Credentials** > Klik **Create Credentials** > Pilih **OAuth client ID**.
   - Application type: **Desktop app**.
   - Name: `AIClipperUploader`.
5. Klik tombol **Download JSON** pada OAuth Client ID yang baru dibuat.
6. Ubah nama file JSON yang diunduh menjadi **`client_secrets.json`**.
7. Simpan file tersebut ke lokasi berikut:
   ```
   ai-clipper-bot/config/tokens/client_secrets.json
   ```
8. Saat bot dijalankan pertama kali, jendela browser authorization akan terbuka untuk autentikasi satu kali. File token refresh akan otomatis tersimpan di `config/tokens/youtube_token.json`.

---

## 5. Setup Cookie Upload TikTok Native

Untuk mengunggah video ke TikTok secara headless menggunakan Playwright tanpa membutuhkan API resmi:

1. Buka browser (Chrome/Edge) dan login ke akun TikTok Anda di [tiktok.com](https://www.tiktok.com).
2. Install ekstensi Chrome bernama **Get cookies.txt LOCALLY** atau ekstensi sejenis untuk mengexport cookie browser.
3. Export cookie dari domain `tiktok.com` dalam format **JSON**.
4. Simpan file cookie tersebut ke lokasi berikut:
   ```
   ai-clipper-bot/config/tokens/tiktok_cookies.json
   ```

*(Catatan: Jika file `client_secrets.json` atau `tiktok_cookies.json` belum diisi, bot tetap berjalan memproses clipping video & subtitle, namun langkah publishing ke platform terkait akan dilewati dengan aman).*

---

## 6. Pengujian & Eksekusi Lokal

Jalankan perintah berikut di terminal:

```bash
# Mengaktifkan venv (jika belum)
source venv/bin/activate  # (Linux/macOS)
# .\venv\Scripts\activate # (Windows)

# Jalankan engine bot
python main.py
```

### Flow Otomatis yang Berjalan saat Bot Aktif:
1. Membaca feed video terbaru dari `SOURCE_FEED_URL`.
2. Memeriksa database SQLite `bot_state.db`. Jika ID video sudah pernah diproses, bot akan melewatinya secara otomatis.
3. Mengunduh stream audio 16kHz WAV dan stream video 1080p MP4.
4. Transkripsi audio kata-per-kata via **Groq Whisper Large v3**.
5. Deteksi klip paling viral (durasi 25-45 detik dengan hook 3 detik) via **Groq Llama 3.3 70B**.
6. Kalibrasi stempel waktu pemotongan berbasis deteksi hening (**`pydub.silence`**) agar kalimat tidak terpotong di tengah kata.
7. Pembuatan file subtitle animasi `.srt`.
8. Rendering video vertical ratio 9:16 (background blur + foreground overlay + burned-in subtitles) menggunakan 1-pass CPU FFmpeg.
9. Auto-publish ke YouTube Shorts & TikTok.
10. **Atomic Cleanup**: Menghapus seluruh file sementara `.wav`, `.mp4`, `.srt` di `temp/` sehingga disk VPS tidak pernah penuh.
11. Tidur (*sleep*) sesuai jeda waktu `RAMPUP_MODE` (8 jam) atau `STANDARD_MODE` (2.4 jam), lalu mengulang siklus secara otomatis.

---

## 7. Deployment 24/7 di Server Linux (Ubuntu VPS)

Agar bot berjalan 24 jam nonstop di latar belakang server dan menyala otomatis saat VPS direboot:

### 1. Salin Service Systemd
File configurasi service systemd [ai-clipper.service](file:///d:/Achmad%20Roychan/Proyek/New%20folder/generate-conten/ai-clipper-bot/ai-clipper.service) sudah tersedia di folder proyek.

Salin file tersebut ke direktori systemd Linux:
```bash
sudo cp ai-clipper.service /etc/systemd/system/
```

### 2. Aktifkan & Jalankan Service
```bash
# Reload konfig daemon systemd
sudo systemctl daemon-reload

# Aktifkan autostart saat server boot
sudo systemctl enable ai-clipper.service

# Jalankan service bot sekarang
sudo systemctl start ai-clipper.service
```

### 3. Cek Status Service
```bash
sudo systemctl status ai-clipper.service
```

---

## 8. Monitoring Log & Pemeliharaan

### Memantau Log Live via Terminal
- **Menggunakan Journalctl (Systemd)**:
  ```bash
  sudo journalctl -u ai-clipper.service -f -n 100
  ```
- **Menggunakan File Log Bot (`logs/system.log`)**:
  ```bash
  tail -f logs/system.log
  ```

### Menghentikan / Restart Bot
- **Restart Bot**: `sudo systemctl restart ai-clipper.service`
- **Stop Bot**: `sudo systemctl stop ai-clipper.service`
- **Disable Autostart**: `sudo systemctl disable ai-clipper.service`
