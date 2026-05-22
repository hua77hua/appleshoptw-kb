#!/bin/bash

# ── AppleShopTW 知識庫啟動腳本 ──────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "🍎 AppleShopTW 知識庫"
echo "─────────────────────────────────"

# 啟動虛擬環境
source venv/bin/activate

# 確認資料庫存在
if [ ! -d "chroma_db" ]; then
  echo "⚠️  尚未匯入 PDF，正在執行匯入..."
  python ingest.py --pdf_dir ./pdfs
  echo ""
fi

echo "🚀 啟動服務中..."
echo "📌 請打開瀏覽器前往：http://localhost:8000"
echo "⚙️  管理後台：http://localhost:8000/admin"
echo ""
echo "（按 Ctrl+C 可停止服務）"
echo "─────────────────────────────────"
echo ""

uvicorn app:app --host 0.0.0.0 --port 8000
