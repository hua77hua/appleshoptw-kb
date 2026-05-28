"""
ingest.py — PDF 批次解析 & 向量化匯入 ChromaDB
支援繁體中文 / 英文 PDF，自動依資料夾分類

用法:
    python ingest.py --pdf_dir ./pdfs --reset
    python ingest.py --pdf_dir ./pdfs          # 增量匯入（不清除舊資料）

PDF 放置方式（資料夾名稱即分類標籤）:
    pdfs/
    ├── Safari/        ← 分類名稱
    │   ├── safari_guide.pdf
    │   └── ...
    ├── 新手教學/
    └── iCloud/
"""

import os
import sys
import argparse
import hashlib
from pathlib import Path
from tqdm import tqdm

import pdfplumber
import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

# ─── 設定 ──────────────────────────────────────────────────────────
CHROMA_PATH   = "./chroma_db"
COLLECTION    = "knowledge_base"
CHUNK_SIZE    = 400
CHUNK_OVERLAP = 80
# ────────────────────────────────────────────────────────────────────


def extract_text_from_pdf(pdf_path: Path) -> list[dict]:
    """用 pdfplumber 逐頁擷取文字"""
    pages = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text and text.strip():
                    pages.append({"page": i + 1, "text": text.strip()})
    except Exception as e:
        print(f"  ⚠️  無法解析 {pdf_path.name}: {e}")
    return pages


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """將長文字切成有重疊的段落"""
    chunks, start = [], 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


def get_categories(pdf_dir: Path) -> list[str]:
    """掃描資料夾，回傳所有分類（子資料夾名稱）"""
    cats = [d.name for d in pdf_dir.iterdir() if d.is_dir()]
    # 根目錄下直接放的 PDF 歸類為「其他」
    direct = [f for f in pdf_dir.glob("*.pdf")]
    if direct:
        cats.append("其他")
    return sorted(cats)


def file_id(path: Path) -> str:
    """用 MD5 作為檔案唯一識別碼，避免重複匯入"""
    return hashlib.md5(path.read_bytes()).hexdigest()


def ingest(pdf_dir: str, reset: bool = False):
    pdf_root = Path(pdf_dir)
    if not pdf_root.exists():
        print(f"❌ 找不到資料夾: {pdf_dir}")
        sys.exit(1)

    # ── 初始化 ChromaDB（使用內建輕量嵌入模型）────────────────────────────
    db = chromadb.PersistentClient(path=CHROMA_PATH)
    ef = DefaultEmbeddingFunction()
    if reset:
        print("🗑  清除舊資料庫...")
        try:
            db.delete_collection(COLLECTION)
        except Exception:
            pass
    collection = db.get_or_create_collection(
        name=COLLECTION,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"}
    )

    print("✅ 使用 ChromaDB 內建嵌入模型（輕量，無需 torch）")

    # ── 收集所有 PDF 路徑 + 分類 ────────────────────────────────────
    pdf_tasks: list[tuple[Path, str]] = []
    for pdf_file in pdf_root.rglob("*.pdf"):
        relative = pdf_file.relative_to(pdf_root)
        parts = relative.parts
        category = parts[0] if len(parts) > 1 else "其他"
        pdf_tasks.append((pdf_file, category))

    print(f"\n📂 找到 {len(pdf_tasks)} 份 PDF，開始匯入...\n")

    total_chunks = 0
    skipped = 0

    for pdf_path, category in tqdm(pdf_tasks, desc="處理 PDF", unit="份"):
        fid = file_id(pdf_path)

        # 檢查是否已匯入
        existing = collection.get(where={"file_id": fid}, limit=1)
        if existing["ids"] and not reset:
            skipped += 1
            continue

        pages = extract_text_from_pdf(pdf_path)
        if not pages:
            continue

        ids, docs, metas = [], [], []
        chunk_idx = 0

        for page_data in pages:
            chunks = chunk_text(page_data["text"])
            for chunk in chunks:
                if len(chunk.strip()) < 20:
                    continue
                uid = f"{fid}_{chunk_idx}"
                ids.append(uid)
                docs.append(chunk)
                metas.append({
                    "file_id":  fid,
                    "filename": pdf_path.name,
                    "category": category,
                    "page":     page_data["page"],
                    "source":   str(pdf_path),
                })
                chunk_idx += 1

        if ids:
            batch_size = 200
            for i in range(0, len(ids), batch_size):
                collection.upsert(
                    ids=ids[i:i+batch_size],
                    documents=docs[i:i+batch_size],
                    metadatas=metas[i:i+batch_size],
                )
            total_chunks += len(ids)

    print(f"\n✅ 匯入完成！")
    print(f"   新增段落: {total_chunks}")
    print(f"   略過(已存在): {skipped}")
    print(f"   資料庫總筆數: {collection.count()}")


def list_categories():
    """列出目前資料庫中所有分類"""
    db = chromadb.PersistentClient(path=CHROMA_PATH)
    try:
        col = db.get_collection(COLLECTION)
        all_meta = col.get(include=["metadatas"])["metadatas"]
        cats = sorted(set(m["category"] for m in all_meta if m))
        print("📂 目前分類：")
        for c in cats:
            print(f"   • {c}")
    except Exception:
        print("⚠️  資料庫尚未建立，請先執行 ingest。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PDF → ChromaDB 知識庫匯入工具")
    parser.add_argument("--pdf_dir", default="./pdfs", help="PDF 根目錄（子資料夾=分類）")
    parser.add_argument("--reset",   action="store_true", help="清除後重新匯入")
    parser.add_argument("--list_cats", action="store_true", help="列出現有分類")
    args = parser.parse_args()

    if args.list_cats:
        list_categories()
    else:
        ingest(args.pdf_dir, reset=args.reset)
