# ☁️ Panduan Lengkap & Mudah: Cara Mendapatkan & Mengatur Server Cloud Gratis (VPS)

Panduan ini dirancang khusus untuk pemula yang belum pernah memiliki server cloud. Bot `ai-clipper-bot` 100% hemat daya dan **TIDAK membutuhkan GPU**, sehingga sangat cocok dijalankan di VPS Gratis.

---

## 📌 PILIHAN PENYEDIA VPS GRATIS

| Penyedia Cloud | Jenis Gratis | Spesifikasi | Cocok Untuk |
| :--- | :--- | :--- | :--- |
| **Oracle Cloud Always Free** *(Sangat Direkomendasikan)* | **Gratis Selamanya ($0)** | Up to 4 CPU, 24 GB RAM, 200 GB Storage, Ubuntu 24.04 | 24/7 Nonstop seumur hidup tanpa biaya |
| **DigitalOcean / Vultr** | **Saldo Gratis $100 - $200** (Trial 60 Hari) | 1 CPU, 1-2 GB RAM, Ubuntu 24.04 | Uji coba cepat tanpa verifikasi rumit |
| **PC / Laptop Pribadi** | **Tanpa Kartu Kredit** | Spesifikasi Laptop Anda | Alternatif jika belum punya VPS saat ini |

---

## 🚀 PANDUAN STEP-BY-STEP: ORACLE CLOUD ALWAYS FREE (GRATIS SELAMANYA)

### Langkah 1: Pendaftaran Akun Oracle Cloud
1. Buka situs resmi: [oracle.com/cloud/free/](https://www.oracle.com/cloud/free/)
2. Klik tombol **Start for free**.
3. Isi data diri Anda (Nama, Email, dan Negara: **Indonesia**).
4. Pilih **Home Region** (Disarankan pilih region terdekat seperti: **Singapore (ap-singapore-1)**).
5. Pada tahap pembayaran/verifikasi, masukkan informasi Kartu Debit/Kredit (Visa/Mastercard, Jenius, Bank Jago, Mandiri, dll).  
   *(Oracle hanya akan melakukan tahan saldo sementara sekitar $1 USD untuk verifikasi identitas dan langsung dikembalikan secara otomatis. Akun Always Free **tidak akan menagih biaya apapun**).*

---

### Langkah 2: Membuat VPS Baru (Instance Ubuntu)
1. Setelah login ke Dashboard Oracle Cloud, buka menu **Compute > Instances**.
2. Klik **Create Instance**.
3. Beri Nama Server, misal: `ai-clipper-server`.
4. Pada bagian **Image and Shape**:
   - Klik **Edit**.
   - Image: Pilih **Canonical Ubuntu 24.04 LTS**.
   - Shape: Pilih **Ampere (Arm)** atau **VM.Standard.E2.1.Micro (AMD Always Free)**.
5. Pada bagian **Save SSH Keys**:
   - Pilih **Generate a key pair for me**.
   - Klik **Save Private Key** (File `.key` atau `.pem` ini akan terunduh ke komputer Anda, simpan dengan baik!).
6. Klik tombol **Create** di bagian bawah.
7. Tunggu 1-2 menit hingga status berubah dari *Provisioning* menjadi hijau (**Running**).
8. Catat **Public IP Address** server Anda (Contoh: `140.238.xx.xx`).

---

### Langkah 3: Remot / Terhubung ke VPS via Terminal Windows

Buka **PowerShell** atau **CMD** di laptop Windows Anda, lalu ketik perintah berikut:

```powershell
# Ganti C:\path\to\private_key.key dengan lokasi file key yang diunduh tadi
# Ganti 140.238.xx.xx dengan Public IP VPS Oracle Anda
ssh -i "C:\path\to\private_key.key" ubuntu@140.238.xx.xx
```

Jika muncul pertanyaan `Are you sure you want to continue connecting (yes/no)?`, ketik **`yes`** lalu tekan Enter. Anda sekarang sudah masuk ke dalam server cloud Linux Anda! 🎉

---

### Langkah 4: Upload & Jalankan Bot di VPS (Cukup 5 Perintah)

Setelah berhasil masuk ke terminal VPS (`ubuntu@ai-clipper-server:~$`):

```bash
# 1. Update server & install dependensi dasar
sudo apt update && sudo apt install -y python3-pip python3-venv ffmpeg git

# 2. Upload/Clone folder ai-clipper-bot ke VPS
git clone <URL-REPOSITORY-ANDA> ai-clipper-bot
cd ai-clipper-bot

# 3. Buat Virtual Environment & install library
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium

# 4. Buat file .env dan masukkan 10 API Key Groq Anda
nano .env
# (Paste isi file .env Anda, lalu tekan Ctrl+O, Enter, Ctrl+X untuk menyimpan)

# 5. Jalankan Bot 24/7 di latar belakang menggunakan Systemd Service
sudo cp ai-clipper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ai-clipper.service
sudo systemctl start ai-clipper.service
```

Selesai! Bot `ai-clipper-bot` kini sudah bekerja 24 jam nonstop di cloud server tanpa bergantung pada PC lokal Anda!

---

## 💻 ALTERNATIF B: Menjalankan di Laptop/PC Pribadi Tanpa VPS

Jika Anda belum ingin mendaftar VPS hari ini, Anda **tetap bisa menjalankan bot ini di laptop/PC Windows Anda sendiri**:

1. Buka PowerShell di folder `ai-clipper-bot`.
2. Aktifkan environment: `.\venv\Scripts\activate`
3. Jalankan bot: `python main.py`
4. Bot akan bekerja memotong video dan mengunggahnya selama laptop Anda menyala & terhubung ke internet. Jika laptop dimatikan, bot akan pause dan bisa dilanjutkan kapan saja saat laptop dinyalakan kembali!
