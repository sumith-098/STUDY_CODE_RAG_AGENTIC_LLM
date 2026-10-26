"""
vector_store.py  --  ChromaDB me documents ka "meaning-based search" (RAG ka retrieval part).

Har chunk: text + embedding (numbers) + metadata (source, page, file_hash, workspace_id).
Har user (workspace_id) ke documents alag rehte hain -- search me dusre ka data kabhi nahi aata.
"""
import hashlib

import chromadb

from . import config
from .documents import build_chunks
from .errors import BadInput
from .llm import get_gateway
from .rate_limiter import estimate_tokens

config.DATA_DIR.mkdir(parents=True, exist_ok=True)
# PersistentClient(path=str) -> disk par save hone wala Chroma database.
_db = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
# Naya collection naam: embedding model/size badle to purane vectors se clash na ho.
# get_or_create_collection(name, metadata) -> Collection. 'hnsw:space': 'cosine' => cosine distance.
_collection = _db.get_or_create_collection(
    name=f"study_documents_{config.EMBEDDING_DIMENSIONS}", metadata={"hnsw:space": "cosine"})


def _ws_filter(workspace_id: str, file_hash: str | None = None) -> dict:
    """Returns: Chroma 'where' filter -- sirf is workspace (aur optional file) ke chunks."""
    if file_hash:
        return {"$and": [{"workspace_id": workspace_id}, {"file_hash": file_hash}]}
    return {"workspace_id": workspace_id}


def index_file(workspace_id: str, filename: str, file_bytes: bytes) -> dict:
    """
    File ko chunks me tod kar embed karta hai aur Chroma me save karta hai.

    Inputs: workspace_id, filename, file_bytes.
    Returns: {'file_hash': str, 'chunks': int, 'already_indexed': bool}
    Quota bachaane ke liye: same file dobara upload ho to embedding dobara nahi hoti.
    """
    file_hash = hashlib.sha256(file_bytes).hexdigest()[:20]
    # collection.get(where, limit, include) -> {'ids': [...]}; include=[] => sirf IDs, data nahi.
    existing = _collection.get(where=_ws_filter(workspace_id, file_hash), include=[])
    if existing["ids"]:
        return {"file_hash": file_hash, "chunks": len(existing["ids"]), "already_indexed": True}

    chunks = build_chunks(filename, file_bytes)
    if not chunks:
        return {"file_hash": file_hash, "chunks": 0, "already_indexed": False}
    total_tokens = sum(estimate_tokens(c["text"]) for c in chunks)
    if total_tokens > config.MAX_EMBED_TOKENS_PER_UPLOAD:
        raise BadInput("This document is too large for the free tier. Please split it into smaller files "
                       "(up to about 100 pages each) and upload them separately.")

    gateway = get_gateway()
    vectors: list[list[float]] = []
    for i in range(0, len(chunks), config.EMBED_BATCH_SIZE):       # 32-32 chunks ek request me
        batch = [c["text"] for c in chunks[i:i + config.EMBED_BATCH_SIZE]]
        vectors.extend(gateway.embed(batch, "RETRIEVAL_DOCUMENT"))

    ws_prefix = hashlib.sha256(workspace_id.encode()).hexdigest()[:8]
    # collection.upsert(ids, documents, embeddings, metadatas) -> None
    #   ids        : har chunk ki unique ID (list[str])
    #   documents  : chunk text (list[str])
    #   embeddings : vectors (list[list[float]])
    #   metadatas  : har chunk ka dict (sirf str/int/float/bool values)
    _collection.upsert(
        ids=[f"{ws_prefix}-{file_hash}-{i}" for i in range(len(chunks))],
        documents=[c["text"] for c in chunks],
        embeddings=vectors,
        metadatas=[{"source": c["source"], "page": int(c["page"]),
                    "chunk_on_page": int(c["chunk_on_page"]),
                    "file_hash": file_hash, "workspace_id": workspace_id} for c in chunks])
    return {"file_hash": file_hash, "chunks": len(chunks), "already_indexed": False}


def search_chunks(workspace_id: str, queries: list[str], top_k: int = 5) -> list[dict]:
    """
    Inputs: workspace_id, queries (1-3 search lines; ek hi embed request me jaati hain), top_k.
    Returns: [{'text','source','page','distance'}] -- distance kam = zyada relevant.
             Duplicate chunks hata diye jaate hain; RETRIEVAL_MAX_DISTANCE se door wale ignore.
    """
    total = len(_collection.get(where=_ws_filter(workspace_id), include=[])["ids"])
    queries = [q.strip() for q in queries if q and q.strip()][:3]
    if total == 0 or not queries:
        return []
    vectors = get_gateway().embed(queries, "RETRIEVAL_QUERY")
    # collection.query(query_embeddings, n_results, where, include) ->
    #   {'documents': [[...]], 'metadatas': [[...]], 'distances': [[...]]}  (har query ke liye ek list)
    result = _collection.query(query_embeddings=vectors, n_results=min(top_k, total),
                               where=_ws_filter(workspace_id),
                               include=["documents", "metadatas", "distances"])
    seen, hits = set(), []
    for q in range(len(queries)):
        for text, meta, dist in zip(result["documents"][q], result["metadatas"][q],
                                    result["distances"][q]):
            key = (meta.get("file_hash"), meta.get("page"), meta.get("chunk_on_page"))
            if key in seen or dist > config.RETRIEVAL_MAX_DISTANCE:
                continue
            seen.add(key)
            hits.append({"text": text, "source": meta.get("source", "Unknown"),
                         "page": meta.get("page", 1), "distance": round(dist, 4)})
    hits.sort(key=lambda h: h["distance"])
    return hits[:top_k]


def list_documents(workspace_id: str) -> list[dict]:
    """Returns: [{'file_hash','name','chunks'}] -- is workspace ki indexed files."""
    data = _collection.get(where=_ws_filter(workspace_id), include=["metadatas"])
    files: dict[str, dict] = {}
    for meta in data["metadatas"]:
        f = files.setdefault(meta["file_hash"], {"file_hash": meta["file_hash"],
                                                 "name": meta["source"], "chunks": 0})
        f["chunks"] += 1
    return sorted(files.values(), key=lambda f: f["name"].lower())


def delete_document(workspace_id: str, file_hash: str) -> None:
    """Inputs: workspace_id, file_hash. Us file ke saare chunks delete. Returns None."""
    _collection.delete(where=_ws_filter(workspace_id, file_hash))


def collection_count() -> int:
    """Returns: poore database me total chunks (health check ke liye)."""
    return _collection.count()