# Knowledge Base — PDF 知識庫系統

一套支援 **繁體中文 + 英文** 的 PDF 知識庫，具備語意搜尋、AI 摘要回覆、分類瀏覽功能。

---

## 📦 安裝

```bash
cd kb_system
pip install -r requirements.txt
```

---

## 📂 放置 PDF

將 PDF 依分類放入子資料夾（**資料夾名稱 = 分類標籤**）：

```
pdfs/
├── 新手教學/
│   ├── 快速入門指南.pdf
│   └── 基礎操作.pdf
├── Safari/
│   ├── safari_beginner.pdf
│   └── safari_advanced.pdf
├── iCloud/
│   └── icloud_setup.pdf
└── 系統設定/
    └── settings_guide.pdf
```

---

## 🔄 匯入 PDF（建立向量資料庫）

```bash
# 首次匯入
python ingest.py --pdf_dir ./pdfs

# 重置並重新匯入（資料有更新時）
python ingest.py --pdf_dir ./pdfs --reset

# 查看目前分類
python ingest.py --list_cats
```

> ⏳ 300 份 PDF 大約需要 10-30 分鐘（取決於 PDF 頁數）

---

## 🚀 啟動服務

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

打開瀏覽器：**http://localhost:8000**

---

## 🤖 啟用 LLM 摘要（選用）

建立 `.env` 檔案：

```env
# OpenAI
LLM_API_KEY=sk-xxxxx
LLM_MODEL=gpt-4o-mini

# 或 Apple 內部 GenAI（替換 base URL）
LLM_API_BASE=https://your-apple-genai-endpoint/v1
LLM_API_KEY=your-key
LLM_MODEL=your-model-name
```

若未設定 LLM，系統仍可正常搜尋，只是不產生摘要回覆。

---

## 🌐 API 說明

| 方法 | 路徑 | 說明 |
|------|------|------|
| `GET` | `/api/categories` | 取得所有分類 |
| `GET` | `/api/articles?category=Safari` | 列出分類文件 |
| `POST` | `/api/search` | 語意搜尋 |
| `POST` | `/api/upload` | 上傳 PDF |

### POST /api/search

```json
{
  "question": "Safari 如何新增書籤？",
  "category": "Safari",   // 可省略（搜全部）
  "top_k": 6
}
```

---

## 🗂️ 專案結構

```
kb_system/
├── app.py          # FastAPI 後端
├── ingest.py       # PDF 匯入工具
├── requirements.txt
├── README.md
├── .env            # LLM 設定（自行建立）
├── chroma_db/      # 向量資料庫（自動產生）
├── pdfs/           # PDF 存放區
│   ├── 新手教學/
│   └── Safari/
└── static/
    └── index.html  # Web UI
```
