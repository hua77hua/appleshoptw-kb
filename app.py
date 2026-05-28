"""
app.py — FastAPI 後端
提供:
  GET  /api/categories          → 取得所有分類
  POST /api/search              → 語意搜尋 / 自由問答
  GET  /api/articles?category=  → 依分類列出所有文章
  POST /api/upload              → 上傳 PDF 並自動匯入（選用）
  GET  /                        → 回傳 index.html
"""

import os
import json
import shutil
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

# 選用：OpenAI-compatible LLM (Apple GenAI / OpenAI / Ollama)
try:
    from openai import OpenAI
    LLM_ENABLED = True
except ImportError:
    LLM_ENABLED = False

load_dotenv()

# ─── 設定 ──────────────────────────────────────────────────────────
CHROMA_PATH    = "./chroma_db"
COLLECTION     = "knowledge_base"
TOP_K          = 6
PDF_UPLOAD_DIR = "./pdfs"
STATIC_DIR     = "./static"

LLM_API_BASE   = os.getenv("LLM_API_BASE", "https://api.openai.com/v1")
LLM_API_KEY    = os.getenv("LLM_API_KEY",  "sk-xxx")
LLM_MODEL      = os.getenv("LLM_MODEL",    "gpt-4o-mini")
# ────────────────────────────────────────────────────────────────────

app = FastAPI(title="PDF 知識庫 API", version="1.0.0")

# ── 全域初始化（啟動時執行一次）──────────────────────────────────────
print("🗄  連線 ChromaDB...")
ef = DefaultEmbeddingFunction()
db = chromadb.PersistentClient(path=CHROMA_PATH)
try:
    collection = db.get_collection(COLLECTION, embedding_function=ef)
    print(f"✅ 資料庫已載入，共 {collection.count()} 筆段落")
except Exception:
    collection = None
    print("⚠️  資料庫尚未建立，請先執行 ingest.py")

if LLM_ENABLED and LLM_API_KEY != "sk-xxx":
    llm_client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_API_BASE)
    print(f"🤖 LLM 已啟用: {LLM_MODEL}")
else:
    llm_client = None
    print("💡 LLM 未設定，將只回傳相關段落（無摘要生成）")


# ── Pydantic Models ───────────────────────────────────────────────────
class SearchRequest(BaseModel):
    question: str
    category: Optional[str] = None   # None = 全部分類
    top_k: Optional[int] = TOP_K


class SearchResult(BaseModel):
    chunk:    str
    filename: str
    category: str
    page:     int
    score:    float


class SearchResponse(BaseModel):
    answer:  str
    results: list[SearchResult]


# ── Helper: 語意搜尋 ──────────────────────────────────────────────────
def semantic_search(question: str, category: Optional[str], top_k: int) -> list[dict]:
    if collection is None:
        raise HTTPException(status_code=503, detail="資料庫尚未建立，請先執行 ingest.py")

    query_emb = ef([question])
    where = None
    if category and category not in ("all", "全部"):
        where = {"category": {"$eq": category}}

    results = collection.query(
        query_embeddings=query_emb,
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    hits = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        hits.append({
            "chunk":    doc,
            "filename": meta.get("filename", ""),
            "category": meta.get("category", ""),
            "page":     meta.get("page", 0),
            "score":    round(1 - dist, 4),   # cosine similarity
        })
    return hits


# ── Helper: LLM 摘要 ─────────────────────────────────────────────────
def generate_answer(question: str, context_chunks: list[str]) -> str:
    if llm_client is None:
        return ""

    context = "\n\n---\n\n".join(context_chunks[:4])
    system_prompt = (
        "你是一個專業的客服助理，根據以下文件內容（可能是繁體中文或英文），"
        "用繁體中文簡潔回答使用者問題。\n"
        "如果文件內容不足以回答，請說明「目前文件中找不到相關資訊」。\n"
        "不要自行編造內容。"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": f"文件內容：\n{context}\n\n問題：{question}"},
    ]
    try:
        resp = llm_client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            max_tokens=600,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"（LLM 回覆失敗：{e}）"


# ── API Routes ────────────────────────────────────────────────────────

@app.get("/api/categories")
def get_categories():
    """取得資料庫中所有分類標籤"""
    if collection is None:
        return {"categories": []}
    all_meta = collection.get(include=["metadatas"])["metadatas"]
    cats = sorted(set(m["category"] for m in all_meta if m))
    return {"categories": cats}


@app.get("/api/articles")
def get_articles(category: Optional[str] = None):
    """依分類列出文章（去重 by filename）"""
    if collection is None:
        return {"articles": []}

    where = None
    if category and category not in ("all", "全部"):
        where = {"category": {"$eq": category}}

    result = collection.get(where=where, include=["metadatas"])
    seen, articles = set(), []
    for m in result["metadatas"]:
        if not m:
            continue
        key = m.get("filename", "")
        if key not in seen:
            seen.add(key)
            articles.append({
                "filename": m.get("filename", ""),
                "category": m.get("category", ""),
                "source":   m.get("source", ""),
            })
    articles.sort(key=lambda x: x["filename"])
    return {"articles": articles}


def get_full_pdf_text(source_path: str) -> str:
    """直接讀取 PDF 全文"""
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(source_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text and text.strip():
                    text_parts.append(f"── 第 {i+1} 頁 ──\n{text.strip()}")
        return "\n\n".join(text_parts)
    except Exception as e:
        return ""


@app.post("/api/search", response_model=SearchResponse)
def search(req: SearchRequest):
    """語意搜尋：找最相關 PDF，直接回傳全文"""
    hits = semantic_search(req.question, req.category, req.top_k or TOP_K)
    if not hits:
        return SearchResponse(answer="找不到相關資料，請嘗試其他關鍵字。", results=[])

    # 取最高分的 PDF，嘗試讀取全文
    best = hits[0]
    full_text = ""
    if best.get("source"):
        full_text = get_full_pdf_text(best["source"])

    if full_text:
        answer = f"📄 {best['filename'].replace('.pdf', '')}\n\n{full_text}"
    else:
        # fallback：合併所有命中段落
        parts = []
        seen = set()
        for h in hits:
            key = h["filename"] + str(h["page"])
            if key not in seen:
                seen.add(key)
                parts.append(f"── {h['filename'].replace('.pdf','')} 第 {h['page']} 頁 ──\n{h['chunk'].strip()}")
        answer = "\n\n".join(parts)

    return SearchResponse(
        answer=answer,
        results=[SearchResult(**h) for h in hits],
    )


@app.post("/api/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    category: str = Form("其他"),
):
    """上傳單份 PDF 並即時匯入"""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="只接受 PDF 檔案")

    save_dir = Path(PDF_UPLOAD_DIR) / category
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / file.filename

    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # 非同步觸發 ingest（簡化版：直接呼叫 ingest 邏輯）
    import subprocess, sys
    subprocess.Popen(
        [sys.executable, "ingest.py", "--pdf_dir", PDF_UPLOAD_DIR],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    return {"status": "ok", "message": f"✅ {file.filename} 已上傳，正在背景匯入..."}


# ── 靜態檔案 & SPA fallback ──────────────────────────────────────────
# ⚠️ /api/pdf 必須在 app.mount 之前定義，否則 mount 會攔截請求

@app.get("/api/pdf")
async def serve_pdf(category: str = "", filename: str = ""):
    """直接讀取 PDF bytes 回傳，繞過路由攔截問題"""
    from fastapi.responses import Response
    import urllib.parse

    # decode 可能的 URL encoding
    cat  = urllib.parse.unquote(category)
    fname = urllib.parse.unquote(filename)

    pdf_path = Path(PDF_UPLOAD_DIR) / cat / fname
    if not pdf_path.exists():
        # 全域搜尋
        matches = list(Path(PDF_UPLOAD_DIR).rglob(fname))
        if matches:
            pdf_path = matches[0]
        else:
            return Response(content=f"找不到: {cat}/{fname}", status_code=404)

    data = pdf_path.read_bytes()
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline"},
    )

app.mount("/pdfs", StaticFiles(directory=PDF_UPLOAD_DIR), name="pdfs")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(f"{STATIC_DIR}/index.html")
