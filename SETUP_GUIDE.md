# 📱 PANDUAN SETUP LENGKAP: 24/7 AI CLIPPER ENGINE & PWA DASHBOARD

Dokumentasi ini berisi panduan **langkah-demi-langkah (step-by-step)** dari nol untuk mendeploy **ai-clipper-bot** di server cloud gratisan (Oracle Cloud VPS), menghubungkan Cloudflare Tunnel (domain HTTPS gratis), serta meng-install Dashboard PWA ke smartphone (Android / iOS) dan Laptop Anda.

---

## 🏗️ ARSITEKTUR KESELURUHAN SISTEM

* **🤖 Bot Engine (`main.py`)**: Berjalan 24 jam nonstop di latar belakang server, memindai YouTube viral, mengevaluasi *Viral Hook Score > 90*, mengekstrak klip, membuat subtitle animasi CapCut (ASS), dan merender video Full HD 1080x1920 (9:16).
* **🌐 Web Dashboard PWA (`dashboard/server.py`)**: Web Server FastAPI ringan yang melayani antarmuka PWA (Progressive Web App).
* **🔒 Cloudflare Tunnel**: Menghubungkan dashboard ke URL HTTPS gratis yang aman agar dapat dibuka dari HP/Laptop mana saja via koneksi internet seluler/WiFi.

---

## ☁️ TAHAP 1: PILIHAN SERVER CLOUD (ALTERNATIF TERBAIK TANPA ORACLE)

Karena registrasi Oracle Cloud sering mengalami kendala (verifikasi kartu ditolak / stok server habis), berikut adalah **3 Alternatif Terbaik & Jauh Lebih Mudah**:

---

### 🌟 OPSIONAL A: DigitalOcean / Vultr (Saldo Gratis $200 USD / Rp 3 Juta)
* **Keunggulan**: Pendaftaran 100% lancar, pilihan lokasi Singapore melimpah, tidak pernah *out of capacity*.
* **Cara Klaim Saldo $200 Gratis (Trial 60 Hari)**:
  1. Daftar di **[digitalocean.com](https://www.digitalocean.com)** (atau via GitHub Student Pack jika punya).
  2. Saat registrasi, Anda akan diberikan bonus saldo gratis **$200 USD**.
  3. Buat **Droplet (VPS)**:
     - OS: **Ubuntu 24.04 LTS**
     - Plan: **Basic ($4 - $6/bulan)** - *Otomatis terpotong dari saldo $200 gratisan*.
     - Region: **Singapore**.
  4. Catat **IP Address** VPS Anda untuk remote via SSH.

---

### 🇮🇩 OPSIONAL B: VPS Indonesia Lokal (Tanpa Kartu Kredit - Bayar via QRIS/GoPay)
Jika Anda tidak ingin menggunakan kartu kredit sama sekali:
* **Penyedia**: **IDCloudHost**, **Biznet Gio (NEO Lite)**, atau **Dewaweb**.
* **Biaya**: Murah meriah (~Rp 30.000 – Rp 50.000 / bulan).
* **Keunggulan**: Pembayaran bisa pakai **QRIS, GoPay, ShopeePay, DANA, atau Bank Lokal**. Kecepatan internet ke YouTube Indonesia sangat cepat & tidak perlu verifikasi rumit.
* **Spesifikasi disarankan**: 1 CPU, 1 GB / 2 GB RAM, Ubuntu 24.04 LTS.

---

### 💻 OPSIONAL C: Menjalankan di PC/Laptop Rumah + Cloudflare Tunnel (100% Gratis Rp 0)
Jika Anda ingin mencoba gratis 100% tanpa bayar dan tanpa kartu kredit:
1. Jalankan bot & dashboard di laptop/PC Windows Anda sendiri.
2. Gunakan **Cloudflare Tunnel** atau **Tailscale** agar Dashboard PWA di laptop Anda tetap bisa dibuka dari HP di mana saja saat laptop menyala.

---

---

## 💻 TAHAP 2: DEPLOY BOT & DASHBOARD DI SERVER (24/7 NONSTOP)

### Langkah 2.1: Remot Server via PowerShell / Terminal
Buka PowerShell di laptop Anda dan masuk ke server:
```powershell
ssh -i "C:\path\to\private_key.key" ubuntu@140.238.xx.xx
```

### Langkah 2.2: Install Dependensi & Clone Project
Setelah masuk ke terminal server Ubuntu:
```bash
# 1. Update paket server & install dependensi dasar
sudo apt update && sudo apt install -y python3-pip python3-venv ffmpeg git curl

# 2. Clone repository project Anda
git clone https://github.com/Arroychaan/ai-clipper-bot.git ai-clipper-bot
cd ai-clipper-bot

# 3. Buat Virtual Environment & install library
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. Generate PWA Icons
python dashboard/static/icons/generate_icons.py
```

### Langkah 2.3: Buat File Konfigurasi `.env`
Ketik perintah berikut untuk membuat file `.env`:
```bash
nano .env
```
Isikan konfigurasi berikut (sesuaikan API Key Groq dan Feed YouTube target Anda):
```env
# 10 Groq API Keys (Rotasi Otomatis)
GROQ_KEY_1=gsk_xxxxxxxxxxxxxxxx
GROQ_KEY_2=gsk_xxxxxxxxxxxxxxxx

# Filter Viral Hook Score (Hanya klip super-elite > 90 yang diambil)
MIN_VIRAL_SCORE=90

# Target YouTube Channel Feed
SOURCE_FEED_URL=https://www.youtube.com/@DennySumargo/videos
TARGET_LANGUAGE=id

# Dashboard Password
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8000
DASHBOARD_PASSWORD=admin123
```
*Tekan `Ctrl + O`, `Enter`, lalu `Ctrl + X` untuk menyimpan.*

### Langkah 2.4: Setup Service 24/7 (Systemd)

Buat Service untuk **Bot Engine**:
```bash
sudo nano /etc/systemd/system/ai-clipper.service
```
Tempelkan konfigurasi ini:
```ini
[Unit]
Description=AI Clipper Bot 24/7 Engine
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/ai-clipper-bot
ExecStart=/home/ubuntu/ai-clipper-bot/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Buat Service untuk **Web Dashboard**:
```bash
sudo nano /etc/systemd/system/ai-dashboard.service
```
Tempelkan konfigurasi ini:
```ini
[Unit]
Description=AI Clipper PWA Dashboard
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/ai-clipper-bot
ExecStart=/home/ubuntu/ai-clipper-bot/venv/bin/python dashboard/server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Jalankan kedua service agar bekerja 24 jam nonstop:
```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-clipper ai-dashboard
sudo systemctl start ai-clipper ai-dashboard
```

Cek status service:
```bash
sudo systemctl status ai-clipper
sudo systemctl status ai-dashboard
```

---

## 🔒 TAHAP 3: SETUP CLOUDFLARE TUNNEL (DOMAIN HTTPS GRATIS UNTUK HP)

Persyaratan PWA dan penginstalan di smartphone membutuhkan koneksi aman **HTTPS**. Kita bisa menggunakan Cloudflare Tunnel secara 100% gratis.

### Langkah 3.1: Install Cloudflared di Server
```bash
# Download & install cloudflared
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb
```

### Langkah 3.2: Jalankan Quick Tunnel Gratis
Jalankan perintah berikut untuk mengekspos Dashboard ke URL HTTPS gratis:
```bash
cloudflared tunnel --url http://localhost:8000
```
Terminal akan menampilkan URL HTTPS gratis, contoh:
`https://xxx-xxx-xxx.trycloudflare.com`

*Tips: Agar Cloudflare Tunnel berjalan permanen 24/7 sebagai service, jalankan perintah:*
```bash
sudo cloudflared service install
```

---

## 📱 TAHAP 4: CARA INSTALL DASHBOARD PWA DI SMARTPHONE & LAPTOP

### Di Smartphone (Android / iPhone):
1. Buka browser Chrome / Safari di HP Anda.
2. Masukkan URL Cloudflare Tunnel Anda (misal: `https://xxx-xxx-xxx.trycloudflare.com`).
3. Pada browser Android Chrome, tekan tombol **"Install App"** di bagian atas navbar Dashboard atau buka menu titik tiga > **"Add to Home screen"** / **"Install App"**.
4. Pada iPhone Safari, tekan tombol **Share (Bagikan)** > gulir ke bawah dan pilih **"Add to Home Screen"** (*Tambah ke Layar Utama*).
5. Aplikasi **AI Clipper** kini muncul di layar utama HP Anda dengan icon resmi, beraksi seperti aplikasi bawaan (standalone full screen)!

### Di Windows / Mac Laptop:
1. Buka URL HTTPS di Google Chrome / Microsoft Edge.
2. Klik ikon instalasi di sebelah kanan address bar Chrome atau klik tombol **Install App** pada Dashboard.

---

## 📱 ALUR WORKFLOW HARIAN ANDA:
1. **AI Bekerja 24/7**: Server mengeklip video viral dan mengumpulkan klip ber-score > 90 di Dashboard.
2. **Buka PWA App di HP**: Buka aplikasi AI Clipper dari layar utama HP Anda.
3. **Filter & Preview**: Pilih klip status `📥 Siap Upload`, tonton preview Full HD 9:16.
4. **1-Click Copy**: Tekan tombol **"Copy Caption & Tagar"** untuk menyalin caption minimalis & hashtag viral.
5. **1-Click Download**: Tekan tombol **"Download"** untuk mengunduh MP4 Full HD langsung ke galeri HP.
6. **Upload Manual**: Buka TikTok / Shorts / Reels di HP, upload video, paste caption, dan publish!
7. **Mark Post**: Tekan **"Mark Post"** di Dashboard PWA agar klip berpindah ke tab `✅ Sudah Post`.

---

## 🛠️ COMMAND PERAWATAN & MONITORING SERVER

```bash
# Melihat log aktivitas bot mengeklip video secara real-time
sudo journalctl -u ai-clipper -f

# Melihat log aktivitas web dashboard
sudo journalctl -u ai-dashboard -f

# Restart bot jika ada perubahan konfigurasi
sudo systemctl restart ai-clipper
sudo systemctl restart ai-dashboard
```
