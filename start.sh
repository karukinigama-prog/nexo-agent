#!/bin/bash
# ──────────────────────────────────────────────────────────
#  Nexo AI Agent — Setup & Run Script
# ──────────────────────────────────────────────────────────
set -e

echo ""
echo "  ███╗   ██╗███████╗██╗  ██╗ ██████╗ "
echo "  ████╗  ██║██╔════╝╚██╗██╔╝██╔═══██╗"
echo "  ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║"
echo "  ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║"
echo "  ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝"
echo "  ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ "
echo ""
echo "  AI Software Building Agent"
echo "──────────────────────────────────────"
echo ""

# Check GROQ_API_KEY
if [ -z "$GROQ_API_KEY" ]; then
  echo "⚠  GROQ_API_KEY is not set!"
  echo "   Export it: export GROQ_API_KEY=gsk_..."
  exit 1
fi

echo "✅ GROQ_API_KEY detected."
echo ""
echo "📦 Installing Python dependencies..."
pip install -r requirements.txt --quiet --disable-pip-version-check

echo "🎭 Installing Playwright + Chromium..."
playwright install chromium --with-deps 2>/dev/null || playwright install chromium

echo ""
echo "🚀 Starting Nexo on http://0.0.0.0:7860 ..."
echo "   Open your browser → http://localhost:7860"
echo ""

python main.py
