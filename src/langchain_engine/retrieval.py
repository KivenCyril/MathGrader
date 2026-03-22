from typing import Any, Dict, List, Optional

from src.langchain_engine.retrieval_backends import WeaviateHybridRecommendationService


class HybridRecommendationService:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        lc_cfg = self.config.get("langchain", {}) or {}
        rec_cfg = lc_cfg.get("recommendation", {}) or {}
        backend = str(rec_cfg.get("backend") or "weaviate").strip().lower()
        if backend != "weaviate":
            raise RuntimeError(f"unsupported recommendation backend: {backend}. Only 'weaviate' is supported.")
        self._backend = WeaviateHybridRecommendationService(self.config)

        self.enabled = bool(self._backend.enabled)
        self.backend_name = str(getattr(self._backend, "backend_name", backend) or backend)

    def recommend(self, **kwargs):
        return self._backend.recommend(**kwargs)

    def list_dataset_ids(self) -> List[str]:
        return self._backend.list_dataset_ids()

    def build_index(
        self,
        dataset_id: str,
        *,
        force_rebuild: bool = False,
        progress_callback=None,
    ) -> Dict[str, Any]:
        return self._backend.build_index(
            dataset_id,
            force_rebuild=force_rebuild,
            progress_callback=progress_callback,
        )
