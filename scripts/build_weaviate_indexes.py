import argparse
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.langchain_engine.retrieval import HybridRecommendationService
from src.services.config_service import ConfigService


def _format_dataset_line(index: int, total: int, dataset_id: str) -> str:
    return f"[{index}/{total}] {dataset_id}"


def _make_progress_callback(index: int, total: int, dataset_id: str, *, plain_log: bool = False):
    last_progress = {"text": ""}

    def callback(event: Dict[str, Any]) -> None:
        phase = str(event.get("phase") or "").strip()
        if phase == "prepare":
            text = f"{_format_dataset_line(index, total, dataset_id)} | preparing collection"
        elif phase == "snapshot":
            doc_total = int(event.get("totalDocs") or 0)
            text = f"{_format_dataset_line(index, total, dataset_id)} | snapshot ready | docs {doc_total}"
        elif phase == "embed":
            embedded = int(event.get("embeddedDocs") or 0)
            doc_total = int(event.get("totalDocs") or 0)
            batch_index = int(event.get("batchIndex") or 0)
            batch_total = int(event.get("totalBatches") or 0)
            progress = float(event.get("progress") or 0.0)
            text = (
                f"{_format_dataset_line(index, total, dataset_id)} | "
                f"embed {progress:6.2f}% | docs {embedded}/{doc_total} | batches {batch_index}/{batch_total}"
            )
        elif phase == "import":
            imported = int(event.get("importedDocs") or 0)
            doc_total = int(event.get("totalDocs") or 0)
            batch_index = int(event.get("batchIndex") or 0)
            batch_total = int(event.get("totalBatches") or 0)
            progress = float(event.get("progress") or 0.0)
            text = (
                f"{_format_dataset_line(index, total, dataset_id)} | "
                f"{progress:6.2f}% | docs {imported}/{doc_total} | batches {batch_index}/{batch_total}"
            )
        else:
            text = f"{_format_dataset_line(index, total, dataset_id)} | {phase or 'working'}"

        if text != last_progress["text"]:
            if plain_log:
                print(text, flush=True)
            else:
                print(f"\r{text}", end="", flush=True)
            last_progress["text"] = text

    return callback


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Weaviate indexes for all usable math datasets.")
    parser.add_argument("--config", default="settings.yaml", help="Path to YAML config file.")
    parser.add_argument("--dataset", action="append", default=[], help="Specific dataset_id to build. Can be passed multiple times.")
    parser.add_argument("--force-rebuild", action="store_true", help="Delete and rebuild existing collections.")
    parser.add_argument("--plain-log", action="store_true", help="Write progress as newline-delimited logs instead of in-place updates.")
    args = parser.parse_args()

    config = ConfigService(args.config).config
    service = HybridRecommendationService(config)
    if service.backend_name != "weaviate":
        raise RuntimeError(f"current recommendation backend is {service.backend_name}, expected weaviate")

    dataset_ids: List[str] = [str(x).strip() for x in (args.dataset or []) if str(x).strip()]
    if not dataset_ids:
        dataset_ids = service.list_dataset_ids()
    if not dataset_ids:
        print("No usable datasets found under data_root.")
        return 1

    print(f"Datasets to build: {len(dataset_ids)}")
    for idx, dataset_id in enumerate(dataset_ids, start=1):
        print(_format_dataset_line(idx, len(dataset_ids), dataset_id))
        started_at = time.perf_counter()
        result = service.build_index(
            dataset_id,
            force_rebuild=bool(args.force_rebuild),
            progress_callback=_make_progress_callback(idx, len(dataset_ids), dataset_id, plain_log=bool(args.plain_log)),
        )
        elapsed = time.perf_counter() - started_at
        if not args.plain_log:
            print("\r", end="")
        print(
            f"{_format_dataset_line(idx, len(dataset_ids), dataset_id)} | done | "
            f"docs {result['totalDocs']} | collection {result['collectionName']} | {elapsed:.2f}s"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
