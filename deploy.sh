#!/bin/bash
# ==============================================================================
# 🚀 1-CLICK AUTOMATED DEPLOYMENT SCRIPT FOR AI-CLIPPER-BOT (24/7 ZERO-COST)
# ==============================================================================

set -e

echo "=================================================================="
echo "⚡ Starting 1-Click Automated Setup for ai-clipper-bot..."
echo "=================================================================="

# 1. Update OS packages & install system requirements
echo "📦 [1/5] Updating system packages & installing FFmpeg, Python3, Git..."
sudo apt update && sudo apt install -y python3-pip python3-venv ffmpeg git curl

# 2. Setup Virtual Environment
echo "🐍 [2/5] Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# 3. Install Python production dependencies
echo "📚 [3/5] Installing Python libraries from requirements.txt..."
pip install --upgrade pip
pip install -r requirements.txt

# 4. Generate PWA Icons
echo "🎨 [4/5] Generating PWA icons..."
python dashboard/static/icons/generate_icons.py

# 5. Register Systemd Services for 24/7 Autostart & Self-Healing Recovery
echo "🛠️ [5/5] Configuring 24/7 Systemd Services (ai-clipper & ai-dashboard)..."
sudo cp ai-clipper.service /etc/systemd/system/
if [ -f "ai-dashboard.service" ]; then
    sudo cp ai-dashboard.service /etc/systemd/system/
fi
sudo systemctl daemon-reload
sudo systemctl enable ai-clipper.service ai-dashboard.service || sudo systemctl enable ai-clipper.service
sudo systemctl restart ai-clipper.service
if systemctl list-unit-files | grep -q ai-dashboard.service; then
    sudo systemctl restart ai-dashboard.service
fi

echo "=================================================================="
echo "✅ DEPLOYMENT COMPLETED SUCCESSFULLY!"
echo "=================================================================="
echo "Bot status:"
sudo systemctl status ai-clipper.service --no-pager
echo ""
echo "To monitor live logs, run: sudo journalctl -u ai-clipper.service -f"
echo "To monitor dashboard logs, run: sudo journalctl -u ai-dashboard.service -f"
echo "=================================================================="

