# 📋 PANDUAN EKSEKUSI TERUPDATE 2026: SETUP SISA 3 AKUN & RAHASIA GITHUB

Dokumentasi ini berisi **panduan langkah-demi-langkah (step-by-step) terupdate tahun 2026** untuk menyelesaikan konfigurasi sisa 3 akun Anda (YouTube Indonesia, TikTok Global, TikTok Indonesia) dan menyambungkannya ke GitHub Secrets.

---

## 🎯 DAFTAR TUGAS YANG HARUS DILAKUKAN (CHECKLIST)

- [x] **10 Groq API Key** (`GROQ_KEY_1` s/d `GROQ_KEY_10`) — **SELESAI**
- [x] **YouTube Account 1 (Global)** (`YOUTUBE_TOKEN_GLOBAL_BASE64`) — **SELESAI**
- [ ] **YouTube Account 2 (Indonesia)** (`YOUTUBE_TOKEN_INDO_BASE64`) — **BELUM**
- [ ] **TikTok Account 1 (Global)** (`TIKTOK_COOKIES_GLOBAL_BASE64`) — **BELUM**
- [ ] **TikTok Account 2 (Indonesia)** (`TIKTOK_COOKIES_INDO_BASE64`) — **BELUM**
- [ ] **Target URL Channel YouTube** (`GLOBAL_FEED_URL` & `INDO_FEED_URL`) — **BELUM**
- [ ] **Teks Link Afiliasi Komentar** (`AFFILIATE_COMMENT_TEXT`) — **BELUM**

---

## 🔑 TAHAP 1: SETUP YOUTUBE ACCOUNT 2 (MARKET INDONESIA)

### Langkah A: Buat OAuth Credentials
1. Buka browser Chrome Incognito, login ke **Google/Gmail Akun YouTube Indonesia Anda**.
2. Masuk ke **[Google Cloud Console (console.cloud.google.com)](https://console.cloud.google.com/)**.
3. Buat Project Baru (misal: `AIClipperIndo`).
4. Buka **APIs & Services > Library** > Cari **YouTube Data API v3** > Klik **Enable**.
5. Buka **APIs & Services > OAuth consent screen**:
   - User Type: **External** > Klik **Create**.
   - App Name: `AIClipperIndo` > Masukkan email Anda.
   - Pada bagian **Test Users**, klik **+ ADD USERS** > Masukkan email Gmail akun YouTube Indonesia Anda > Klik **Save**.
6. Buka **APIs & Services > Credentials** > Klik **Create Credentials** > **OAuth client ID**:
   - Application Type: **Desktop App** > Klik **Create**.
7. Download file JSON, rename menjadi **`client_secrets.json`**, lalu replace/simpan di:
   `ai-clipper-bot/config/tokens/client_secrets.json`

### Langkah B: Jalankan Login & Ambil Base64 Token
1. Di terminal PowerShell PC Anda, aktifkan venv dan jalankan perintah login:
   ```powershell
   cd "D:\Achmad Roychan\Proyek\New folder\generate-conten\ai-clipper-bot"
   .\venv\Scripts\activate
   python -c "from uploader.youtube_uploader import YouTubeUploader; YouTubeUploader()"
   ```
2. Login & klik **Allow** di browser yang terbuka. File `youtube_token.json` baru akan tercipta.
3. Konversi file token tersebut ke Base64:
   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("config/tokens/youtube_token.json"))
   ```
4. Copy teks Base64 tersebut, buka **[GitHub Secrets](https://github.com/Arroychaan/ai-clipper-bot/settings/secrets/actions)**:
   - Klik **New repository secret**.
   - Name: `YOUTUBE_TOKEN_INDO_BASE64`
   - Secret: Paste teks Base64 -> Klik **Add secret**.

---

## 🎵 TAHAP 2: SETUP TIKTOK ACCOUNT 1 (GLOBAL)

1. Buka browser Chrome, pastikan Anda login ke **Akun TikTok Global (Luar Negeri)** Anda di **[tiktok.com](https://www.tiktok.com)**.
2. Install ekstensi Chrome: **[Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)** dari Chrome Web Store.
3. Buka tab `tiktok.com`, buka ekstensi tersebut, lalu klik **Export Cookies as JSON**.
4. Rename/Simpan file cookie tersebut sebagai **`tiktok_cookies.json`** di folder:
   `ai-clipper-bot/config/tokens/tiktok_cookies.json`
5. Konversi file cookie ke Base64 via PowerShell:
   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("config/tokens/tiktok_cookies.json"))
   ```
6. Copy teks Base64 tersebut, buka **[GitHub Secrets](https://github.com/Arroychaan/ai-clipper-bot/settings/secrets/actions)**:
   - Klik **New repository secret**.
   - Name: `TIKTOK_COOKIES_GLOBAL_BASE64`
   - Secret: Paste teks Base64 -> Klik **Add secret**.

---

## 🎵 TAHAP 3: SETUP TIKTOK ACCOUNT 2 (INDONESIA)

1. Buka browser Chrome, buka tab baru (atau Incognito), login ke **Akun TikTok Indonesia** Anda di **[tiktok.com](https://www.tiktok.com)**.
2. Buka ekstensi **Get cookies.txt LOCALLY**, klik **Export Cookies as JSON**.
3. Simpan file cookie tersebut sebagai **`tiktok_cookies.json`** di folder `config/tokens/`.
4. Konversi file cookie ke Base64 via PowerShell:
   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("config/tokens/tiktok_cookies.json"))
   ```
5. Copy teks Base64 tersebut, buka **[GitHub Secrets](https://github.com/Arroychaan/ai-clipper-bot/settings/secrets/actions)**:
   - Klik **New repository secret**.
   - Name: `TIKTOK_COOKIES_INDO_BASE64`
   - Secret: Paste teks Base64 -> Klik **Add secret**.

---

## 📌 TAHAP 4: SETUP FEED TARGET & LINK AFILIASI (GITHUB SECRETS)

Di halaman **[GitHub Secrets](https://github.com/Arroychaan/ai-clipper-bot/settings/secrets/actions)**, tambahkan 3 secret berikut:

1. **`GLOBAL_FEED_URL`**:
   - Value: `https://www.youtube.com/@HubermanLab/videos` (atau URL podcast luar negeri pilihan Anda).
2. **`INDO_FEED_URL`**:
   - Value: `https://www.youtube.com/@DennySumargo/videos` (atau URL podcast Indonesia pilihan Anda).
3. **`AFFILIATE_COMMENT_TEXT`**:
   - Value: `🛒 Dapatkan produk yang dibahas di video ini di sini: https://shope.ee/xxx` (Text link afiliasi Shopee/TikTok Shop Anda).

---

## 🚀 TAHAP 5: EKSEKUSI PENUH 4 AKUN AUTO-PUBLISH

Setelah seluruh 7 Secrets di atas terpasang di GitHub:
1. Buka **[GitHub Actions](https://github.com/Arroychaan/ai-clipper-bot/actions)**.
2. Jalankan kedua workflow:
   - **`🌍 AI Clipper Bot - Global Market Pipeline`** (untuk YouTube Global + TikTok Global).
   - **`🇮🇩 AI Clipper Bot - Indonesia Market Pipeline`** (untuk YouTube Indo + TikTok Indo + Auto Comment Afiliasi).

Seluruh sistem 4 akun akan langsung berjalan otomatis 24/7 di Cloud tanpa henti!
