"""
OAuth Token Generator — Run this on your LOCAL machine (NOT on VPS).

This script authenticates with YouTube via pytubefix OAuth and saves
the token cache that you can then copy to your VPS.

Usage:
  1. Run this script on your local machine: python generate_oauth_token.py
  2. Follow the URL in your browser to authenticate with a Google account
  3. The token will be saved to config/oauth_cache/tokens.json
  4. Copy this file to your VPS at the same path

IMPORTANT: Use a secondary/burner Google account, NOT your primary account.
"""

import os
import sys
import shutil
from pathlib import Path

def main():
    try:
        import pytubefix
    except ImportError:
        print("❌ pytubefix is not installed. Run: pip install pytubefix")
        sys.exit(1)

    # Setup paths
    base_dir = Path(__file__).resolve().parent
    oauth_cache_dir = base_dir / "config" / "oauth_cache"
    os.makedirs(oauth_cache_dir, exist_ok=True)

    print("=" * 60)
    print("🔐 YouTube OAuth Token Generator for AI Clipper Bot")
    print("=" * 60)
    print()
    print("⚠️  PENTING: Gunakan akun Google SEKUNDER/CADANGAN!")
    print("   Jangan gunakan akun Google utama Anda.")
    print()

    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    print("📡 Memulai autentikasi OAuth via pytubefix...")
    print("   Ikuti instruksi di terminal untuk login via browser.")
    print()

    try:
        yt = pytubefix.YouTube(
            test_url,
            client='WEB',
            use_oauth=True,
            allow_oauth_cache=True
        )
        # Trigger the auth flow by accessing streams
        title = yt.title
        print(f"\n✅ Autentikasi berhasil! Video: {title}")
    except Exception as e:
        print(f"\n❌ Autentikasi gagal: {e}")
        sys.exit(1)

    # Find the cached token file
    # pytubefix stores it in its package __cache__ directory
    ptf_dir = Path(pytubefix.__file__).parent
    ptf_cache = ptf_dir / "__cache__" / "tokens.json"

    target_file = oauth_cache_dir / "tokens.json"

    if ptf_cache.exists():
        shutil.copy2(ptf_cache, target_file)
        print(f"\n✅ Token disalin ke: {target_file}")
    else:
        # Try to find it in common locations
        possible = [
            ptf_dir / "__cache__",
            Path.home() / ".pytubefix" / "tokens.json",
        ]
        found = False
        for p in possible:
            token_path = p / "tokens.json" if p.is_dir() else p
            if token_path.exists():
                shutil.copy2(token_path, target_file)
                print(f"\n✅ Token ditemukan di {token_path} dan disalin ke: {target_file}")
                found = True
                break

        if not found:
            print(f"\n⚠️  Token cache tidak ditemukan secara otomatis.")
            print(f"   Cari file 'tokens.json' di folder pytubefix:")
            print(f"   {ptf_dir}")
            print(f"   Lalu salin ke: {target_file}")

    print()
    print("=" * 60)
    print("📋 LANGKAH SELANJUTNYA:")
    print("=" * 60)
    print(f"1. Upload file ini ke VPS:")
    print(f"   scp {target_file} root@YOUR_VPS_IP:/root/ai-clipper-bot/config/oauth_cache/tokens.json")
    print()
    print("2. Restart service di VPS:")
    print("   systemctl restart ai-clipper && systemctl restart ai-dashboard")
    print()
    print("3. Token akan otomatis digunakan oleh bot sebagai Layer 3 defense.")
    print("=" * 60)


if __name__ == "__main__":
    main()
