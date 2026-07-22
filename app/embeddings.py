"""교체형 임베딩 백엔드.

- openai  : text-embedding-3-small  (OPENAI_API_KEY)
- voyage  : voyage-3                (VOYAGE_API_KEY)
- hashing : 오프라인 폴백(결정론적). 키 없이 파이프라인/테스트 구동용.
            한국어는 char bigram 으로 분해해 약한 부분문자열 겹침을 확보하지만,
            진짜 의미 인접성은 API 백엔드에서만 제대로 나옴.

`(backend, text_hash) -> vector` 를 embedding_cache 에 저장해 재계산·API 비용을 줄인다.
"""
import hashlib
import json
import os
import re

import httpx


# ---------------- 백엔드 구현 ----------------

class EmbeddingBackend:
    name = "base"

    def embed(self, texts):
        raise NotImplementedError


class HashingEmbedding(EmbeddingBackend):
    name = "hashing"

    def __init__(self, dim=384):
        self.dim = dim

    @staticmethod
    def _tokens(text):
        text = (text or "").lower()
        toks = []
        for w in re.findall(r"[a-z0-9]+|[가-힣]+", text):
            if re.fullmatch(r"[가-힣]+", w) and len(w) >= 2:
                toks += [w[i:i + 2] for i in range(len(w) - 1)]  # char bigram
            toks.append(w)
        return toks

    def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * self.dim
            for tok in self._tokens(t):
                h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
                v[h % self.dim] += 1.0
            out.append(v)
        return out


class _HttpEmbedding(EmbeddingBackend):
    url = ""
    model = ""
    env_key = ""

    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or os.environ.get(self.env_key)
        if model:
            self.model = model
        if not self.api_key:
            raise RuntimeError(f"{self.env_key} 가 설정되지 않았습니다.")

    def embed(self, texts):
        r = httpx.post(
            self.url,
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            json={"model": self.model, "input": list(texts)},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()["data"]
        data.sort(key=lambda d: d["index"])
        return [d["embedding"] for d in data]


class LocalEmbedding(EmbeddingBackend):
    """로컬 sentence-transformers 다국어 모델. 키·과금 없이 진짜 의미 매칭.

    첫 호출 시 모델을 로드(최초 1회 다운로드). 모델은 환경변수 LOCAL_EMBED_MODEL
    로 교체 가능(기본: 다국어 MiniLM).
    """
    name = "local"
    default_model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self, model=None):
        self.model_name = model or os.environ.get("LOCAL_EMBED_MODEL", self.default_model)
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, texts):
        m = self._load()
        return m.encode(list(texts), normalize_embeddings=True).tolist()


class OpenAIEmbedding(_HttpEmbedding):
    name = "openai"
    url = "https://api.openai.com/v1/embeddings"
    model = "text-embedding-3-small"
    env_key = "OPENAI_API_KEY"


class VoyageEmbedding(_HttpEmbedding):
    name = "voyage"
    url = "https://api.voyageai.com/v1/embeddings"
    model = "voyage-3"
    env_key = "VOYAGE_API_KEY"


_BACKENDS = {b.name: b for b in
             (HashingEmbedding, LocalEmbedding, OpenAIEmbedding, VoyageEmbedding)}


def _local_available():
    try:
        import sentence_transformers  # noqa: F401
        return True
    except Exception:
        return False


def make_backend(name=None):
    """환경변수 EMBEDDING_BACKEND 또는 키/설치 여부로 자동 선택.

    우선순위: 명시 지정 > OpenAI 키 > Voyage 키 > 로컬 모델 설치됨 > hashing 폴백.
    """
    name = name or os.environ.get("EMBEDDING_BACKEND")
    if not name:
        if os.environ.get("OPENAI_API_KEY"):
            name = "openai"
        elif os.environ.get("VOYAGE_API_KEY"):
            name = "voyage"
        elif _local_available():
            name = "local"
        else:
            name = "hashing"
    return _BACKENDS[name]()


# ---------------- 캐시 래퍼 ----------------

def _hash(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def embed_cached(backend, texts, conn):
    """캐시를 활용해 텍스트 리스트를 임베딩. 반환 순서는 입력과 동일."""
    result = {}
    missing = []
    for t in texts:
        h = _hash(t)
        row = conn.execute(
            "SELECT vector FROM embedding_cache WHERE backend=? AND text_hash=?",
            (backend.name, h),
        ).fetchone()
        if row:
            result[t] = json.loads(row["vector"])
        elif t not in [m[0] for m in missing]:
            missing.append((t, h))

    if missing:
        vecs = backend.embed([m[0] for m in missing])
        for (t, h), v in zip(missing, vecs):
            conn.execute(
                "INSERT OR REPLACE INTO embedding_cache(backend,text_hash,vector) VALUES (?,?,?)",
                (backend.name, h, json.dumps(v)),
            )
            result[t] = v
        conn.commit()

    return [result[t] for t in texts]
