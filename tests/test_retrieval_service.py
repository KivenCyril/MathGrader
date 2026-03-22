import unittest

from src.langchain_engine.retrieval import HybridRecommendationService


class _FakeBackend:
    def __init__(self):
        self.calls = []

    def list_dataset_ids(self):
        self.calls.append(("list_dataset_ids",))
        return ["demo.jsonl"]

    def build_index(self, dataset_id, *, force_rebuild=False, progress_callback=None):
        self.calls.append(("build_index", dataset_id, force_rebuild, progress_callback))
        return {
            "datasetId": dataset_id,
            "forceRebuild": force_rebuild,
        }


class HybridRecommendationServiceTests(unittest.TestCase):
    def _build_service(self):
        service = HybridRecommendationService.__new__(HybridRecommendationService)
        service._backend = _FakeBackend()
        service.backend_name = "fake"
        service.enabled = True
        service.config = {}
        return service

    def test_list_dataset_ids_delegates_to_backend_interface(self):
        service = self._build_service()

        dataset_ids = service.list_dataset_ids()

        self.assertEqual(dataset_ids, ["demo.jsonl"])
        self.assertEqual(service._backend.calls, [("list_dataset_ids",)])

    def test_build_index_delegates_to_backend_interface(self):
        service = self._build_service()
        progress_events = []

        result = service.build_index(
            "demo.jsonl",
            force_rebuild=True,
            progress_callback=progress_events.append,
        )

        self.assertEqual(
            result,
            {
                "datasetId": "demo.jsonl",
                "forceRebuild": True,
            },
        )
        self.assertEqual(
            service._backend.calls,
            [("build_index", "demo.jsonl", True, progress_events.append)],
        )


if __name__ == "__main__":
    unittest.main()
