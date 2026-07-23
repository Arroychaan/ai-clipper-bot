# ♾️ PANDUAN TUNGGAL: DEPLOYMENT SERVER CLOUD GRATIS SELAMANYA (24/7 NONSTOP TANPA LAPTOP)

Dokumentasi ini adalah **satu-satunya panduan resmi dan pasti** untuk mengoperasikan `ai-clipper-bot` secara 100% otomatis, berjalan 24 jam sehari, 365 hari seminggu **GRATIS SELAMANYA ($0 Cost)**, dan **TIDAK TERGANTUNG PADA LAPTOP PRIBADI ANDA**.

Setelah prosedur di bawah selesai dilakukan, Anda dapat **mematikan laptop Anda selamanya** dan bot akan terus memotong serta mengunggah video secara mandiri di cloud.

---

## 📑 DAFTAR LANGKAH SELESAI DARI NOL

1. [Tahap 1: Pendaftaran Server Cloud Gratis Oracle Always Free](#tahap-1-pendaftaran-server-cloud-gratis-oracle-always-free)
2. [Tahap 2: Membuat Instance Server VPS Ubuntu 24.04](#tahap-2-membuat-instance-server-vps-ubuntu-2404)
3. [Tahap 3: Hubungkan Laptop ke Server Cloud via SSH](#tahap-3-hubungkan-laptop-ke-server-cloud-via-ssh)
4. [Tahap 4: Eksekusi 1-Klik Deployment Script](#tahap-4-eksekusi-1-klik-deployment-script)
5. [Tahap 5: Verifikasi 24/7 & Matikan Laptop Anda](#tahap-5-verifikasi-247--matikan-laptop-anda)

---

## 🚀 TAHAP 1: Pendaftaran Server Cloud Gratis Oracle Always Free

Oracle Cloud menyediakan server VPS yang **Gratis Selamanya ($0/bulan)** tanpa batas waktu trial.

1. Buka link resmi pendaftaran: **[oracle.com/cloud/free/](https://www.oracle.com/cloud/free/)**
2. Klik tombol **Start for free**.
3. Isi data pendaftaran:
   - **Country**: Indonesia
   - **Home Region**: Pilih **Singapore (ap-singapore-1)** atau **Tokyo**.
4. **Verifikasi Pembayaran ($0 Billing)**:
   - Masukkan informasi kartu Debit/Kredit (Visa/Mastercard, Jenius, Bank Jago, Mandiri, dll).
   - Oracle akan melakukan *temporary hold* saldo sekitar Rp 15.000 ($1 USD) dan **langsung dikembalikan detik itu juga**.
   - **Jaminan 100% $0**: Akun *Always Free* Oracle tidak memiliki opsi *auto-charge* berbayar kecuali Anda menaikkan status akun secara manual.

---

## ⚡ TAHAP 2: Membuat Instance Server VPS Ubuntu 24.04

1. Setelah masuk ke Dashboard Oracle Cloud Console, buka menu **Compute > Instances**.
2. Klik tombol **Create Instance**.
3. Isi konfigurasi server sebagai berikut:
   - **Name**: `ai-clipper-server`
   - **Image and Shape** (Klik tombol Edit):
     - **Image**: Pilih **Canonical Ubuntu 24.04 LTS** (Wajib).
     - **Shape**: Pilih **Ampere (Arm)** dengan 2 s/d 4 OCPU, 12 s/d 24 GB RAM *(100% Always Free Eligible)*.
   - **Save SSH Keys** (PENTING):
     - Pilih **Generate a key pair for me**.
     - Klik **Save Private Key**. File bernama `ssh-key-xxxx.key` atau `pem` akan terunduh ke komputer Anda. Simpan file ini di folder aman.
4. Klik tombol **Create** di bagian paling bawah.
5. Tunggu 1-2 menit hingga indikator berubah warna menjadi **GREEN (Running)**.
6. Catat **Public IP Address** server Anda (Contoh: `140.238.200.50`).

---

## 💻 TAHAP 3: Hubungkan Laptop ke Server Cloud via SSH

1. Buka **PowerShell** di laptop Windows Anda.
2. Masukkan perintah SSH di bawah ini (sesuaikan path file `.key` dan `Public IP` server Anda):

```powershell
ssh -i "C:\Users\NamaAnda\Downloads\ssh-key-2026-07-23.key" ubuntu@140.238.200.50
```

3. Jika muncul pertanyaan `Are you sure you want to continue connecting (yes/no)?`, ketik **`yes`** lalu tekan Enter.
4. Anda sekarang telah berhasil masuk ke dalam Server Cloud Linux Anda (`ubuntu@ai-clipper-server:~$`).

---

## 📦 TAHAP 4: Eksekusi 1-Klik Deployment Script

Setelah Anda berada di dalam terminal server VPS, jalankan perintah otomatis berikut:

### 1. Download / Upload Kode Bot ke VPS
```bash
# Upload folder proyek ai-clipper-bot ke server VPS atau clone dari repository Anda
git clone <URL-REPOSITORY-ANDA> ai-clipper-bot
cd ai-clipper-bot
```

### 2. Beri Izin & Jalankan Installer 1-Klik (`deploy.sh`)
```bash
# Beri izin eksekusi script
chmod +x deploy.sh

# Jalankan installer otomatis 1-klik
./deploy.sh
```

Script `deploy.sh` akan secara otomatis:
- Menginstall paket FFmpeg, Python 3.12, dan Git.
- Mengkonfigurasi Virtual Environment Python.
- Menginstall Playwright Chromium Headless beserta dependensi OS Ubuntu.
- Mendaftarkan dan mengaktifkan **Systemd Auto-Restart Service (`ai-clipper.service`)**.

---

## 🔒 TAHAP 5: Verifikasi 24/7 & Matikan Laptop Anda!

### 1. Cek Status Bot di Server Cloud
Untuk memastikan bot sudah berjalan di latar belakang:
```bash
sudo systemctl status ai-clipper.service
```
Pastikan status menunjukkan **`active (running)`** berwarna hijau.

### 2. Memantau Log Aktivitas Realtime
```bash
sudo journalctl -u ai-clipper.service -f
```

### 3. JAMINAN ABADI 24/7: Matikan Laptop Anda!
Bot `ai-clipper-bot` kini berjalan di dalam server cloud Oracle yang terhubung langsung ke internet 24 jam sehari. 

- **Fitur Self-Healing**: Jika server cloud restart atau mengalami kegagalan sementara, Systemd akan otomatis menyalakan kembali bot dalam 10 detik.
- **Laptop Anda bebas dimatikan, dicabut dari charger, atau dibawa bepergian**. Bot akan terus berjalan secara otomatis 100% tanpa henti selamanya!
