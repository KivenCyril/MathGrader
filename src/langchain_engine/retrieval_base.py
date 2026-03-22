import fnmatch
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.common.coercion import safe_float, safe_int
from src.llm_clients.base_client import LLMClient


class _RecommendationBase:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        lc_cfg = self.config.get("langchain", {}) or {}
        self.rec_cfg = lc_cfg.get("recommendation", {}) or {}

        self.enabled = bool(self.rec_cfg.get("enabled", True))
        self.top_k = max(1, safe_int(self.rec_cfg.get("top_k"), 5))
        self.recommendation_count = max(1, safe_int(self.rec_cfg.get("recommendation_count"), 3))
        self.min_score = safe_float(self.rec_cfg.get("min_score"), 0.05)
        self.lexical_blend = max(0.0, min(1.0, safe_float(self.rec_cfg.get("lexical_blend"), 0.35)))
        self.max_docs = max(1000, safe_int(self.rec_cfg.get("max_docs"), 60000))
        self.vector_candidate_k = max(5, safe_int(self.rec_cfg.get("vector_candidate_k"), 80))
        self.apply_to_datasets = [str(x).strip() for x in (self.rec_cfg.get("apply_to_datasets") or []) if str(x).strip()]

        self._token_pattern = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]+")
        self._number_pattern = re.compile(r"\d+(?:\.\d+)?")

        self.data_root = self._resolve_root(self.rec_cfg.get("data_root"), fallback_candidates=[Path("data/raw"), Path("../data/raw")])

        self._corpus_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._embedding_client_inst: Optional[LLMClient] = None

    def _resolve_root(self, configured_root: Optional[str], fallback_candidates: List[Path]) -> Path:
        if configured_root:
            p = Path(str(configured_root))
            if p.exists():
                return p
        for candidate in fallback_candidates:
            if candidate.exists():
                return candidate
        return fallback_candidates[0]

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
        qid = self._field(item, "id", "problem_id", "_id", "questionId", "question_id") or str(idx + 1)
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

    def _embed_texts(self, texts: List[str]) -> List[List[float]]:
        client = self._get_embedding_client()
        if client is None:
            return []
        try:
            vectors = client.embeddings(texts)
        except Exception:
            vectors = []
        if not isinstance(vectors, list):
            return []
        return vectors

    def _normalize_vector_records(
        self,
        docs: List[Dict[str, Any]],
        vectors: List[Any],
        meta: Optional[Dict[str, Any]] = None,
        source: str = "runtime",
    ) -> Tuple[List[Dict[str, Any]], List[List[float]], Dict[str, Any]]:
        pair_count = min(len(docs), len(vectors), self.max_docs)
        normalized_rows: List[Tuple[Dict[str, Any], List[float]]] = []
        dim_counter: Counter[int] = Counter()

        for idx in range(pair_count):
            doc = docs[idx]
            vector = vectors[idx]
            if not isinstance(doc, dict) or not isinstance(vector, list):
                continue
            try:
                normalized_vector = [float(x) for x in vector]
            except Exception:
                continue
            if not normalized_vector:
                continue
            dim_counter[len(normalized_vector)] += 1
            normalized_rows.append((doc, normalized_vector))

        dominant_dim = dim_counter.most_common(1)[0][0] if dim_counter else 0
        kept_docs: List[Dict[str, Any]] = []
        kept_vectors: List[List[float]] = []
        skipped = 0

        for doc, vector in normalized_rows:
            if len(vector) != dominant_dim:
                skipped += 1
                continue
            kept_docs.append(doc)
            kept_vectors.append(vector)

        normalized_meta = dict(meta or {})
        normalized_meta.update(
            {
                "vectorSource": source,
                "vectorDim": dominant_dim,
                "vectorRowsSeen": len(normalized_rows),
                "vectorRowsKept": len(kept_vectors),
                "vectorRowsSkipped": skipped,
            }
        )
        if dim_counter:
            normalized_meta["vectorDimCounts"] = dict(dim_counter)

        return kept_docs, kept_vectors, normalized_meta

    def list_dataset_ids(self) -> List[str]:
        dataset_ids: List[str] = []
        for path in sorted(self.data_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".json", ".jsonl"}:
                continue
            try:
                dataset_id = path.relative_to(self.data_root).as_posix()
            except Exception:
                continue
            if not self._dataset_allowed(dataset_id):
                continue
            try:
                if self._load_corpus(dataset_id):
                    dataset_ids.append(dataset_id)
            except Exception:
                continue
        return dataset_ids
