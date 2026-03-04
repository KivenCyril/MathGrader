import fnmatch
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.llm_clients.base_client import LLMClient


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


class HybridRecommendationService:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        lc_cfg = self.config.get("langchain", {}) or {}
        self.rec_cfg = lc_cfg.get("recommendation", {}) or {}

        self.enabled = bool(self.rec_cfg.get("enabled", True))
        self.top_k = max(1, _safe_int(self.rec_cfg.get("top_k"), 5))
        self.recommendation_count = max(1, _safe_int(self.rec_cfg.get("recommendation_count"), 3))
        self.min_score = _safe_float(self.rec_cfg.get("min_score"), 0.05)
        self.lexical_blend = max(0.0, min(1.0, _safe_float(self.rec_cfg.get("lexical_blend"), 0.35)))
        self.max_docs = max(1000, _safe_int(self.rec_cfg.get("max_docs"), 60000))
        self.vector_candidate_k = max(5, _safe_int(self.rec_cfg.get("vector_candidate_k"), 80))
        self.apply_to_datasets = [str(x).strip() for x in (self.rec_cfg.get("apply_to_datasets") or []) if str(x).strip()]

        self._token_pattern = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]+")
        self._number_pattern = re.compile(r"\d+(?:\.\d+)?")

        self.data_root = self._resolve_root(self.rec_cfg.get("data_root"))
        self._corpus_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._vector_cache: Dict[str, Dict[str, List[float]]] = {}
        self._embedding_client_inst: Optional[LLMClient] = None

    def _resolve_root(self, configured_root: Optional[str]) -> Path:
        if configured_root:
            p = Path(str(configured_root))
            if p.exists():
                return p
        for candidate in [Path("data/raw"), Path("../data/raw")]:
            if candidate.exists():
                return candidate
        return Path("data/raw")

    def _dataset_allowed(self, dataset_id: Optional[str]) -> bool:
        if not self.apply_to_datasets:
            return True
        if not dataset_id:
            return False
        for pattern in self.apply_to_datasets:
            if fnmatch.fnmatch(str(dataset_id), pattern):
                return True
        return False

    def _resolve_dataset_path(self, dataset_id: str) -> Optional[Path]:
        if not dataset_id:
            return None
        root = self.data_root.resolve()
        path = (root / str(dataset_id)).resolve()
        if not str(path).startswith(str(root)):
            return None
        if not path.exists() or not path.is_file():
            return None
        return path

    def _load_raw(self, path: Path) -> List[Dict[str, Any]]:
        if path.suffix.lower() == ".jsonl":
            rows = []
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            rows.append(obj)
                    except Exception:
                        continue
            return rows

        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except Exception:
            pass

        rows = []
        decoder = json.JSONDecoder()
        content = path.read_text(encoding="utf-8")
        idx = 0
        while idx < len(content):
            while idx < len(content) and content[idx].isspace():
                idx += 1
            if idx >= len(content):
                break
            try:
                obj, next_idx = decoder.raw_decode(content, idx)
                if isinstance(obj, dict):
                    rows.append(obj)
                idx = next_idx
            except Exception:
                idx += 1
        return rows

    def _field(self, item: Dict[str, Any], *keys: str) -> str:
        for key in keys:
            if key in item and item[key] is not None:
                return str(item[key])
        for key, value in item.items():
            for target in keys:
                if key.lower() == target.lower() and value is not None:
                    return str(value)
        return ""

    def _normalize_item(self, item: Dict[str, Any], idx: int) -> Dict[str, Any]:
        qid = self._field(item, "id", "problem_id", "_id") or str(idx + 1)
        question = self._field(item, "original_text", "text", "question", "problem", "body").strip()
        truth = self._field(item, "ans", "answer", "truth", "correct_answer", "solution").strip()
        level = self._field(item, "level", "grade").strip()
        meta = self._field(item, "meta", "subject").strip() or level
        return {
            "questionId": qid,
            "question": question,
            "truth": truth,
            "meta": meta,
            "level": level,
        }

    def _load_corpus(self, dataset_id: str) -> List[Dict[str, Any]]:
        if dataset_id in self._corpus_cache:
            return self._corpus_cache[dataset_id]
        path = self._resolve_dataset_path(dataset_id)
        if not path:
            self._corpus_cache[dataset_id] = []
            return []
        raw = self._load_raw(path)
        normalized = [self._normalize_item(item, i) for i, item in enumerate(raw)]
        normalized = [x for x in normalized if x.get("question")]
        if len(normalized) > self.max_docs:
            normalized = normalized[: self.max_docs]
        self._corpus_cache[dataset_id] = normalized
        return normalized

    def _normalize_text(self, text: str) -> str:
        return "".join(str(text or "").split()).lower()

    def _tokens(self, text: str) -> List[str]:
        return self._token_pattern.findall(self._normalize_text(text))

    def _numbers(self, text: str) -> List[str]:
        return self._number_pattern.findall(self._normalize_text(text))

    def _char_ngrams(self, text: str, n: int = 3) -> List[str]:
        s = self._normalize_text(text)
        if len(s) < n:
            return [s] if s else []
        return [s[i : i + n] for i in range(0, len(s) - n + 1)]

    def _jaccard(self, a: List[str], b: List[str]) -> float:
        sa = set(a)
        sb = set(b)
        if not sa or not sb:
            return 0.0
        return len(sa & sb) / len(sa | sb)

    def _lexical_score(self, query: str, candidate: str) -> float:
        token_score = self._jaccard(self._tokens(query), self._tokens(candidate))
        ngram_score = self._jaccard(self._char_ngrams(query), self._char_ngrams(candidate))
        number_score = self._jaccard(self._numbers(query), self._numbers(candidate))
        return (0.45 * token_score) + (0.35 * ngram_score) + (0.20 * number_score)

    def _cosine(self, a: List[float], b: List[float]) -> float:
        if not a or not b:
            return 0.0
        n = min(len(a), len(b))
        if n == 0:
            return 0.0
        dot = 0.0
        na = 0.0
        nb = 0.0
        for i in range(n):
            x = float(a[i])
            y = float(b[i])
            dot += x * y
            na += x * x
            nb += y * y
        if na <= 0 or nb <= 0:
            return 0.0
        return dot / ((na ** 0.5) * (nb ** 0.5))

    def _get_embedding_client(self) -> Optional[LLMClient]:
        if self._embedding_client_inst is not None:
            return self._embedding_client_inst
        alias = str(self.rec_cfg.get("model_alias") or "").strip()
        if not alias:
            alias = str((self.config.get("roles", {}) or {}).get("reviewer") or "").strip()
        model_cfg = dict(((self.config.get("models", {}) or {}).get(alias, {}) or {}))
        if not model_cfg:
            self._embedding_client_inst = None
            return None
        embedding_model = str(self.rec_cfg.get("embedding_model") or model_cfg.get("embedding_model") or "").strip()
        if embedding_model:
            model_cfg["embedding_model"] = embedding_model
        self._embedding_client_inst = LLMClient(model_cfg)
        return self._embedding_client_inst

    def _embed_query_and_candidates(
        self,
        dataset_id: str,
        query_question: str,
        candidates: List[Dict[str, Any]],
    ) -> Tuple[List[float], Dict[str, List[float]]]:
        client = self._get_embedding_client()
        if client is None:
            return [], {}

        cache = self._vector_cache.setdefault(dataset_id, {})
        missing_ids = []
        missing_texts = []
        for item in candidates:
            qid = str(item.get("questionId") or "")
            if not qid:
                continue
            if qid not in cache:
                missing_ids.append(qid)
                missing_texts.append(str(item.get("question") or ""))

        inputs = [str(query_question or "")]
        inputs.extend(missing_texts)
        try:
            vectors = client.embeddings(inputs)
        except Exception:
            vectors = []
        if not isinstance(vectors, list) or not vectors:
            return [], cache

        query_vec = vectors[0] if vectors else []
        for i, qid in enumerate(missing_ids):
            vec_idx = i + 1
            if vec_idx < len(vectors):
                cache[qid] = vectors[vec_idx]
        return query_vec, cache

    def recommend(
        self,
        dataset_id: Optional[str],
        query_question: str,
        exclude_question_id: Optional[str] = None,
        level: Optional[str] = None,
        top_k: Optional[int] = None,
        recommendation_count: Optional[int] = None,
        min_score: Optional[float] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not self.enabled:
            return [], {"enabled": False, "strategy": "disabled", "datasetId": dataset_id, "matched": 0}
        if not dataset_id or not query_question:
            return [], {"enabled": True, "strategy": "skipped", "datasetId": dataset_id, "matched": 0}
        if not self._dataset_allowed(dataset_id):
            return [], {
                "enabled": True,
                "strategy": "skipped_by_dataset_rule",
                "datasetId": dataset_id,
                "datasetRules": self.apply_to_datasets,
                "matched": 0,
            }

        use_top_k = max(1, _safe_int(top_k, self.top_k))
        use_rec_cnt = max(1, _safe_int(recommendation_count, self.recommendation_count))
        use_min_score = _safe_float(min_score, self.min_score)

        corpus = self._load_corpus(str(dataset_id))
        if not corpus:
            return [], {"enabled": True, "strategy": "empty_corpus", "datasetId": dataset_id, "matched": 0}

        lexical_rows: List[Tuple[float, Dict[str, Any]]] = []
        for item in corpus:
            qid = str(item.get("questionId") or "")
            if exclude_question_id and qid and str(exclude_question_id) == qid:
                continue
            item_level = str(item.get("level") or "").strip()
            if level and item_level and str(level).strip() != item_level:
                continue

            lex = self._lexical_score(query_question, item.get("question", ""))
            lexical_rows.append((lex, item))

        lexical_rows.sort(key=lambda x: x[0], reverse=True)
        candidate_pool = [x[1] for x in lexical_rows[: max(use_top_k, self.vector_candidate_k)]]

        qvec: List[float] = []
        vec_cache: Dict[str, List[float]] = {}
        if candidate_pool:
            qvec, vec_cache = self._embed_query_and_candidates(
                str(dataset_id),
                query_question,
                candidate_pool,
            )

        scored: List[Tuple[float, Dict[str, Any], float, float]] = []
        lexical_map = {str(item.get("questionId") or ""): lex for lex, item in lexical_rows}
        for item in candidate_pool:
            qid = str(item.get("questionId") or "")
            lex = lexical_map.get(qid, 0.0)
            vec = 0.0
            if qvec and qid in vec_cache:
                vec = self._cosine(qvec, vec_cache.get(qid) or [])
            final_score = ((1.0 - self.lexical_blend) * vec) + (self.lexical_blend * lex) if qvec else lex
            if final_score >= use_min_score:
                scored.append((final_score, item, vec, lex))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:use_top_k]
        recommendations = []
        for final_score, item, vec, lex in top[:use_rec_cnt]:
            recommendations.append(
                {
                    "questionId": item.get("questionId"),
                    "question": item.get("question"),
                    "truth": item.get("truth"),
                    "meta": item.get("meta"),
                    "score": round(final_score, 4),
                    "embeddingScore": round(vec, 4),
                    "lexicalScore": round(lex, 4),
                    "reason": "Hybrid similarity (embedding + lexical).",
                }
            )

        meta = {
            "enabled": True,
            "strategy": "hybrid_vector_lexical",
            "datasetId": dataset_id,
            "topK": use_top_k,
            "recommendationCount": use_rec_cnt,
            "matched": len(scored),
            "lexicalBlend": self.lexical_blend,
            "minScore": use_min_score,
            "datasetRules": self.apply_to_datasets,
            "vectorEnabled": bool(qvec),
            "vectorCandidateK": self.vector_candidate_k,
        }
        return recommendations, meta
