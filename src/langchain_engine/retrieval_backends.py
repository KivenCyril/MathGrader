import hashlib
import json
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.common.coercion import safe_bool, safe_float, safe_int
from src.langchain_engine.retrieval_base import _RecommendationBase

try:
    import weaviate
    from weaviate.classes.config import Configure, DataType, Property, Tokenization
    from weaviate.classes.data import DataObject
    from weaviate.classes.query import Filter, HybridFusion, MetadataQuery
except Exception:
    weaviate = None
    Configure = None
    DataType = None
    Property = None
    Tokenization = None
    DataObject = None
    Filter = None
    HybridFusion = None
    MetadataQuery = None

ProgressCallback = Optional[Callable[[Dict[str, Any]], None]]


class WeaviateHybridRecommendationService(_RecommendationBase):
    backend_name = "weaviate"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config=config)
        self.weaviate_cfg = self.rec_cfg.get("weaviate", {}) or {}
        self.collection_prefix = str(self.weaviate_cfg.get("collection_prefix") or "MathGraderSim").strip() or "MathGraderSim"
        self.http_host = str(self.weaviate_cfg.get("http_host") or self.weaviate_cfg.get("host") or "127.0.0.1").strip()
        self.http_port = safe_int(self.weaviate_cfg.get("http_port"), 8088)
        self.http_secure = safe_bool(self.weaviate_cfg.get("http_secure"), False)
        self.grpc_host = str(self.weaviate_cfg.get("grpc_host") or self.weaviate_cfg.get("host") or self.http_host).strip()
        self.grpc_port = safe_int(self.weaviate_cfg.get("grpc_port"), 50051)
        self.grpc_secure = safe_bool(self.weaviate_cfg.get("grpc_secure"), False)
        self.skip_init_checks = safe_bool(self.weaviate_cfg.get("skip_init_checks"), False)
        self.api_key = str(self.weaviate_cfg.get("api_key") or "").strip()
        self.import_batch_size = max(1, safe_int(self.weaviate_cfg.get("import_batch_size"), 128))
        self.embedding_batch_size = max(1, safe_int(self.weaviate_cfg.get("embedding_batch_size"), 64))
        self.query_properties = [str(x).strip() for x in (self.weaviate_cfg.get("query_properties") or ["question"]) if str(x).strip()]
        if not self.query_properties:
            self.query_properties = ["question"]
        self.tokenization_name = str(self.weaviate_cfg.get("question_tokenization") or "trigram").strip().lower()
        self.level_filter_property = str(self.weaviate_cfg.get("level_filter_property") or "level").strip() or "level"
        self.force_rebuild = safe_bool(self.weaviate_cfg.get("force_rebuild"), False)
        self.bm25_b = self.weaviate_cfg.get("bm25_b")
        self.bm25_k1 = self.weaviate_cfg.get("bm25_k1")
        self.vector_index_type = str(self.weaviate_cfg.get("vector_index") or "hnsw").strip().lower()

        self._client = None
        self._bootstrapped_datasets: Dict[str, str] = {}

    def _meta(self, dataset_id: Optional[str], strategy: str, matched: int = 0, **extra: Any) -> Dict[str, Any]:
        payload = {
            "enabled": True,
            "backend": self.backend_name,
            "strategy": strategy,
            "datasetId": dataset_id,
            "matched": matched,
        }
        payload.update(extra)
        return payload

    def _connect(self):
        if weaviate is None:
            raise RuntimeError("weaviate-client is not installed")
        if self._client is not None:
            return self._client

        auth = None
        if self.api_key:
            auth = weaviate.auth.Auth.api_key(self.api_key)

        self._client = weaviate.connect_to_custom(
            http_host=self.http_host,
            http_port=self.http_port,
            http_secure=self.http_secure,
            grpc_host=self.grpc_host,
            grpc_port=self.grpc_port,
            grpc_secure=self.grpc_secure,
            auth_credentials=auth,
            skip_init_checks=self.skip_init_checks,
        )
        return self._client

    def _collection_name(self, dataset_id: str) -> str:
        signature_payload = {
            "dataset_id": str(dataset_id),
            "embedding_model": str(self.rec_cfg.get("embedding_model") or ""),
            "vector_index": self.vector_index_type,
            "tokenization": self.tokenization_name,
            "query_properties": list(self.query_properties),
        }
        signature = json.dumps(signature_payload, ensure_ascii=False, sort_keys=True)
        suffix = hashlib.md5(signature.encode("utf-8", errors="ignore")).hexdigest()[:12]
        return f"{self.collection_prefix}{suffix}"

    def _tokenization(self):
        if Tokenization is None:
            return None
        mapping = {
            "field": Tokenization.FIELD,
            "gse": Tokenization.GSE,
            "gse_ch": Tokenization.GSE_CH,
            "kagome_ja": Tokenization.KAGOME_JA,
            "kagome_kr": Tokenization.KAGOME_KR,
            "lowercase": Tokenization.LOWERCASE,
            "trigram": Tokenization.TRIGRAM,
            "whitespace": Tokenization.WHITESPACE,
            "word": Tokenization.WORD,
        }
        return mapping.get(self.tokenization_name, Tokenization.TRIGRAM)

    def _vector_index_config(self):
        if Configure is None:
            return None
        if self.vector_index_type == "flat":
            return Configure.VectorIndex.flat()
        return Configure.VectorIndex.hnsw()

    def _create_collection(self, client: Any, collection_name: str) -> Any:
        if Configure is None or Property is None or DataType is None:
            raise RuntimeError("weaviate-client config classes are unavailable")

        inverted_index_config = None
        if self.bm25_b is not None or self.bm25_k1 is not None:
            inverted_index_config = Configure.inverted_index(
                bm25_b=safe_float(self.bm25_b, 0.75),
                bm25_k1=safe_float(self.bm25_k1, 1.2),
            )

        client.collections.create(
            name=collection_name,
            properties=[
                Property(
                    name="datasetId",
                    data_type=DataType.TEXT,
                    index_filterable=True,
                    index_searchable=False,
                    tokenization=Tokenization.FIELD,
                    skip_vectorization=True,
                    vectorize_property_name=False,
                ),
                Property(
                    name="questionId",
                    data_type=DataType.TEXT,
                    index_filterable=True,
                    index_searchable=False,
                    tokenization=Tokenization.FIELD,
                    skip_vectorization=True,
                    vectorize_property_name=False,
                ),
                Property(
                    name="question",
                    data_type=DataType.TEXT,
                    index_filterable=False,
                    index_searchable=True,
                    tokenization=self._tokenization(),
                    skip_vectorization=True,
                    vectorize_property_name=False,
                ),
                Property(
                    name="truth",
                    data_type=DataType.TEXT,
                    index_filterable=False,
                    index_searchable=False,
                    tokenization=self._tokenization(),
                    skip_vectorization=True,
                    vectorize_property_name=False,
                ),
                Property(
                    name="meta",
                    data_type=DataType.TEXT,
                    index_filterable=True,
                    index_searchable=True,
                    tokenization=self._tokenization(),
                    skip_vectorization=True,
                    vectorize_property_name=False,
                ),
                Property(
                    name="level",
                    data_type=DataType.TEXT,
                    index_filterable=True,
                    index_searchable=True,
                    tokenization=Tokenization.FIELD,
                    skip_vectorization=True,
                    vectorize_property_name=False,
                ),
            ],
            vector_config=Configure.Vectors.self_provided(vector_index_config=self._vector_index_config()),
            inverted_index_config=inverted_index_config,
        )
        return client.collections.get(collection_name)

    def _stable_uuid(self, dataset_id: str, question_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{dataset_id}:{question_id}"))

    def _collection_total_count(self, collection: Any) -> int:
        total = collection.aggregate.over_all(total_count=True).total_count or 0
        return int(total)

    def _load_index_records(
        self,
        dataset_id: str,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[List[float]], Dict[str, Any]]:
        docs = self._load_corpus(dataset_id)
        if not docs:
            return [], [], {}

        batch_size = self.embedding_batch_size
        vectors: List[List[float]] = []
        total_docs = len(docs)
        total_batches = max(1, (total_docs + batch_size - 1) // batch_size)
        for start in range(0, len(docs), batch_size):
            texts = [str(item.get("question") or "") for item in docs[start : start + batch_size]]
            batch_vectors = self._embed_texts(texts)
            if not batch_vectors:
                raise RuntimeError("failed to build vectors for Weaviate import")
            vectors.extend([[float(x) for x in vec] for vec in batch_vectors[: len(texts)]])
            if progress_callback is not None:
                embedded_docs = min(start + len(texts), total_docs)
                progress_callback(
                    {
                        "phase": "embed",
                        "datasetId": dataset_id,
                        "embeddedDocs": embedded_docs,
                        "totalDocs": total_docs,
                        "batchIndex": (start // batch_size) + 1,
                        "totalBatches": total_batches,
                        "progress": round((100.0 * embedded_docs / total_docs), 2) if total_docs else 100.0,
                    }
                )

        if len(vectors) < len(docs):
            raise RuntimeError("embedding vector count does not match document count")

        normalized_docs, normalized_vectors, meta = self._normalize_vector_records(
            docs=docs[: len(vectors)],
            vectors=vectors[: len(docs)],
            meta={"dataset_id": dataset_id},
            source="runtime",
        )
        if not normalized_docs or not normalized_vectors:
            raise RuntimeError("no consistent-dimension vectors available for Weaviate import")
        return normalized_docs, normalized_vectors, meta

    def _expected_record_count(self, dataset_id: str) -> int:
        return len(self._load_corpus(dataset_id))

    def _import_dataset(
        self,
        client: Any,
        dataset_id: str,
        collection_name: str,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Any:
        if client.collections.exists(collection_name):
            try:
                collection = client.collections.get(collection_name)
                total = self._collection_total_count(collection)
                expected_count = self._expected_record_count(dataset_id)
                if not self.force_rebuild and expected_count > 0 and total == expected_count:
                    return collection
            except Exception:
                pass
            try:
                client.collections.delete(collection_name)
            except Exception:
                pass

        docs, vectors, _ = self._load_index_records(dataset_id, progress_callback=progress_callback)
        if not docs or not vectors:
            raise RuntimeError(f"no indexable records found for dataset {dataset_id}")

        collection = self._create_collection(client, collection_name)
        total_docs = len(docs)
        total_batches = max(1, (total_docs + self.import_batch_size - 1) // self.import_batch_size)

        for start in range(0, len(docs), self.import_batch_size):
            chunk_docs = docs[start : start + self.import_batch_size]
            chunk_vecs = vectors[start : start + self.import_batch_size]
            objects = []
            for item, vector in zip(chunk_docs, chunk_vecs):
                qid = str(item.get("questionId") or "")
                objects.append(
                    DataObject(
                        uuid=self._stable_uuid(dataset_id, qid or str(start)),
                        properties={
                            "datasetId": str(dataset_id),
                            "questionId": qid,
                            "question": str(item.get("question") or ""),
                            "truth": str(item.get("truth") or ""),
                            "meta": str(item.get("meta") or ""),
                            "level": str(item.get("level") or ""),
                        },
                        vector=[float(x) for x in vector],
                    )
                )
            batch = collection.data.insert_many(objects)
            if getattr(batch, "has_errors", False):
                sample_errors = [str(err.message) for _, err in list((batch.errors or {}).items())[:3]]
                raise RuntimeError(f"Weaviate import failed: {'; '.join(sample_errors)}")
            if progress_callback is not None:
                imported_docs = min(start + len(chunk_docs), total_docs)
                progress_callback(
                    {
                        "phase": "import",
                        "datasetId": dataset_id,
                        "collectionName": collection_name,
                        "importedDocs": imported_docs,
                        "totalDocs": total_docs,
                        "batchIndex": (start // self.import_batch_size) + 1,
                        "totalBatches": total_batches,
                        "progress": round((100.0 * imported_docs / total_docs), 2) if total_docs else 100.0,
                    }
                )

        self.force_rebuild = False
        return collection

    def _ensure_collection(
        self,
        dataset_id: str,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Tuple[Any, str]:
        client = self._connect()
        collection_name = self._collection_name(dataset_id)
        if self._bootstrapped_datasets.get(dataset_id) == collection_name and client.collections.exists(collection_name):
            return client.collections.get(collection_name), collection_name
        if client.collections.exists(collection_name) and not self.force_rebuild:
            collection = client.collections.get(collection_name)
            self._bootstrapped_datasets[dataset_id] = collection_name
            return collection, collection_name
        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "prepare",
                    "datasetId": dataset_id,
                    "collectionName": collection_name,
                    "progress": 0.0,
                }
            )
        collection = self._import_dataset(client, dataset_id, collection_name, progress_callback=progress_callback)
        self._bootstrapped_datasets[dataset_id] = collection_name
        return collection, collection_name

    def _build_filters(self, exclude_question_id: Optional[str], level: Optional[str]):
        filters = []
        if exclude_question_id and Filter is not None:
            filters.append(Filter.by_property("questionId").not_equal(str(exclude_question_id)))
        if level and Filter is not None:
            filters.append(Filter.by_property(self.level_filter_property).equal(str(level).strip()))
        if not filters:
            return None
        if len(filters) == 1:
            return filters[0]
        return Filter.all_of(filters)

    def _query_vector(self, query_question: str) -> List[float]:
        vectors = self._embed_texts([str(query_question or "")])
        if not vectors:
            return []
        return [float(x) for x in (vectors[0] or [])]

    def recommend(
        self,
        dataset_id: Optional[str],
        query_question: str,
        exclude_question_id: Optional[str] = None,
        level: Optional[str] = None,
        top_k: Optional[int] = None,
        recommendation_count: Optional[int] = None,
        min_score: Optional[float] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if not self.enabled:
            return [], self._meta(dataset_id, "disabled", matched=0)
        if not dataset_id or not query_question:
            return [], self._meta(dataset_id, "skipped", matched=0)
        if not self._dataset_allowed(dataset_id):
            return [], self._meta(dataset_id, "skipped_by_dataset_rule", matched=0, datasetRules=self.apply_to_datasets)

        use_top_k = max(1, safe_int(top_k, self.top_k))
        use_rec_cnt = max(1, safe_int(recommendation_count, self.recommendation_count))
        use_min_score = safe_float(min_score, self.min_score)

        try:
            collection, collection_name = self._ensure_collection(str(dataset_id), progress_callback=progress_callback)
            query_vec = self._query_vector(query_question)
            filters = self._build_filters(exclude_question_id=exclude_question_id, level=level)
            alpha = max(0.0, min(1.0, 1.0 - self.lexical_blend))
            limit = max(use_top_k, use_rec_cnt, self.vector_candidate_k)

            query_kwargs: Dict[str, Any] = {
                "query": str(query_question or ""),
                "alpha": alpha,
                "query_properties": list(self.query_properties),
                "limit": limit,
                "return_properties": ["questionId", "question", "truth", "meta", "level"],
            }
            if HybridFusion is not None:
                query_kwargs["fusion_type"] = HybridFusion.RELATIVE_SCORE
            if filters is not None:
                query_kwargs["filters"] = filters
            if MetadataQuery is not None:
                query_kwargs["return_metadata"] = MetadataQuery(score=True, explain_score=True, distance=True)
            if query_vec:
                query_kwargs["vector"] = query_vec

            result = collection.query.hybrid(**query_kwargs)
            objects = list(getattr(result, "objects", []) or [])

            recommendations = []
            for obj in objects:
                props = getattr(obj, "properties", {}) or {}
                meta = getattr(obj, "metadata", None)
                score = float(getattr(meta, "score", 0.0) or 0.0) if meta is not None else 0.0
                distance = getattr(meta, "distance", None) if meta is not None else None
                if score > 0.0 and score < use_min_score:
                    continue
                recommendations.append(
                    {
                        "questionId": props.get("questionId"),
                        "question": props.get("question"),
                        "truth": props.get("truth"),
                        "meta": props.get("meta"),
                        "score": round(score, 4),
                        "embeddingScore": round(max(0.0, 1.0 - float(distance)), 4) if distance is not None else 0.0,
                        "lexicalScore": 0.0,
                        "reason": "Hybrid search (Weaviate BM25 + vector).",
                    }
                )
                if len(recommendations) >= use_rec_cnt:
                    break

            return recommendations, self._meta(
                dataset_id,
                "weaviate_hybrid_bm25_vector",
                matched=len(objects),
                topK=use_top_k,
                recommendationCount=use_rec_cnt,
                minScore=use_min_score,
                lexicalBlend=self.lexical_blend,
                vectorEnabled=bool(query_vec),
                vectorCandidateK=self.vector_candidate_k,
                collectionName=collection_name,
                queryAlpha=round(alpha, 4),
            )
        except Exception as exc:
            return [], self._meta(dataset_id, "weaviate_error", matched=0, error=str(exc), vectorEnabled=False)

    def build_index(
        self,
        dataset_id: str,
        *,
        force_rebuild: bool = False,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        previous_force_rebuild = bool(self.force_rebuild)
        try:
            self.force_rebuild = bool(force_rebuild)
            collection, collection_name = self._ensure_collection(str(dataset_id), progress_callback=progress_callback)
            total = self._collection_total_count(collection)
            return {
                "backend": self.backend_name,
                "datasetId": str(dataset_id),
                "collectionName": collection_name,
                "totalDocs": int(total),
                "forceRebuild": bool(force_rebuild),
            }
        finally:
            self.force_rebuild = previous_force_rebuild
