#!/bin/bash
# =============================================================================
# setup_vps_antibot.sh — VPS Anti-Bot Defense Setup
# 
# Installs Node.js (required for pytubefix auto PO Token generation)
# and updates yt-dlp + pytubefix to latest versions.
#
# Run on VPS: bash setup_vps_antibot.sh
# =============================================================================

set -e

echo "============================================="
echo "🛡️  AI Clipper Bot — VPS Anti-Bot Setup"
echo "============================================="
echo ""

# 1. Install Node.js if not present (required for pytubefix PO Token auto-gen)
if command -v node &> /dev/null; then
    NODE_VER=$(node --version)
    echo "✅ Node.js already installed: $NODE_VER"
else
    echo "📦 Installing Node.js v20 LTS..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
    echo "✅ Node.js installed: $(node --version)"
fi

echo ""

# 2. Update pytubefix to latest
echo "📦 Updating pytubefix to latest version..."
if [ -d "/root/ai-clipper-bot/venv" ]; then
    /root/ai-clipper-bot/venv/bin/pip install --upgrade pytubefix
    echo "✅ pytubefix updated: $(/root/ai-clipper-bot/venv/bin/pip show pytubefix | grep Version)"
else
    pip install --upgrade pytubefix
    echo "✅ pytubefix updated"
fi

echo ""

# 3. Update yt-dlp to latest
echo "📦 Updating yt-dlp to latest version..."
if [ -d "/root/ai-clipper-bot/venv" ]; then
    /root/ai-clipper-bot/venv/bin/pip install --upgrade yt-dlp
    echo "✅ yt-dlp updated: $(/root/ai-clipper-bot/venv/bin/pip show yt-dlp | grep Version)"
else
    pip install --upgrade yt-dlp
    echo "✅ yt-dlp updated"
fi

echo ""

# 4. Create OAuth cache directory
mkdir -p /root/ai-clipper-bot/config/oauth_cache
echo "✅ OAuth cache directory ready: /root/ai-clipper-bot/config/oauth_cache/"

echo ""

# 5. Pull latest code
echo "📥 Pulling latest code from GitHub..."
cd /root/ai-clipper-bot
git stash 2>/dev/null || true
git pull origin main
echo "✅ Code updated"

echo ""

# 6. Restart services
echo "🔄 Restarting services..."
systemctl restart ai-clipper 2>/dev/null && echo "✅ ai-clipper restarted" || echo "⚠️  ai-clipper service not found"
systemctl restart ai-dashboard 2>/dev/null && echo "✅ ai-dashboard restarted" || echo "⚠️  ai-dashboard service not found"

echo ""
echo "============================================="
echo "🎉 Setup Complete! Anti-Bot Defense Active"
echo "============================================="
echo ""
echo "Defense Layers:"
echo "  L1: youtube_transcript_api (caption endpoint)"
echo "  L2: pytubefix + Auto PO Token (Node.js: $(node --version 2>/dev/null || echo 'NOT INSTALLED'))"
echo "  L3: pytubefix + OAuth cache ($([ -f /root/ai-clipper-bot/config/oauth_cache/tokens.json ] && echo 'READY' || echo 'NOT CONFIGURED — run generate_oauth_token.py locally'))"
echo "  L4: yt-dlp + cookies + client rotation"
echo "  L5: yt-dlp bare fallback"
echo ""
echo "Untuk mengaktifkan Layer 3 (OAuth):"
echo "  1. Di komputer lokal, jalankan: python generate_oauth_token.py"
echo "  2. Salin config/oauth_cache/tokens.json ke VPS"
echo "  3. Restart: systemctl restart ai-clipper ai-dashboard"
echo ""
