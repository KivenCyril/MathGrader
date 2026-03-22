import copy
import threading
import time
import uuid
from typing import Any, Dict, List, Optional


class GradeJobStore:
    def __init__(self, ttl_sec: int = 1800):
        self.ttl_sec = max(300, int(ttl_sec))
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _clamp_progress(value: Any) -> Optional[float]:
        try:
            return max(0.0, min(100.0, float(value)))
        except Exception:
            return None

    @staticmethod
    def _normalize_status(value: Optional[str]) -> str:
        text = str(value or "").strip().lower()
        if text in {"completed", "complete"}:
            return "done"
        if text == "running":
            return "active"
        return text

    @classmethod
    def _fallback_progress(cls, stage: str, status: Optional[str], current: Any = None) -> Optional[float]:
        current_progress = cls._clamp_progress(current)
        normalized_status = cls._normalize_status(status)
        if normalized_status in {"done", "failed"}:
            return 100.0
        if current_progress is not None:
            return current_progress
        if normalized_status != "active":
            return None

        defaults = {
            "request_received": 100.0,
            "mcp_rubric_parse": 10.0,
            "answer_equivalence": 20.0,
            "rule_fast_path": 100.0,
            "grade_solver": 40.0,
            "grade_solver_skipped": 45.0,
            "grade_supervisor": 75.0,
            "recommendation_retrieval": 90.0,
            "mcp_scoring_analysis": 95.0,
            "score_mapping": 98.0,
        }
        return defaults.get(str(stage or "").strip())

    def create(self, trace_id: str) -> Dict[str, Any]:
        self._prune()
        job_id = uuid.uuid4().hex[:16]
        now = time.time()
        job = {
            "jobId": job_id,
            "traceId": str(trace_id or "").strip(),
            "status": "queued",
            "headline": "判卷任务已提交",
            "items": [
                {
                    "stage": "request_received",
                    "label": "已提交判卷请求",
                    "detail": "后端已接收请求，正在排队处理。",
                    "status": "done",
                    "notes": ["任务已创建，正在准备进入判卷流程。"],
                }
            ],
            "result": None,
            "error": "",
            "createdAt": now,
            "updatedAt": now,
        }
        with self._lock:
            self._jobs[job_id] = job
        return self.snapshot(job_id) or {}

    def start(self, job_id: str, headline: str = "正在判卷处理中") -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["status"] = "running"
            job["headline"] = str(headline or "正在判卷处理中")
            job["updatedAt"] = time.time()

    def update_stage(
        self,
        job_id: str,
        *,
        stage: str,
        label: Optional[str] = None,
        detail: Optional[str] = None,
        status: Optional[str] = None,
        notes: Optional[List[str]] = None,
        progress: Optional[float] = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            items = job.setdefault("items", [])
            item = None
            for current in items:
                if str(current.get("stage") or "") == str(stage or ""):
                    item = current
                    break
            if item is None:
                item = {
                    "stage": str(stage or "").strip(),
                    "label": str(label or stage or "处理阶段").strip() or "处理阶段",
                    "detail": str(detail or "").strip(),
                    "status": str(status or "pending").strip() or "pending",
                    "notes": [],
                    "progress": None,
                }
                items.append(item)
            if label is not None:
                item["label"] = str(label or item.get("label") or "").strip() or "处理阶段"
            if detail is not None:
                item["detail"] = str(detail or "").strip()
            if status is not None:
                item["status"] = str(status or "").strip() or item.get("status") or "pending"
            if notes is not None:
                item["notes"] = [str(note or "").strip() for note in notes if str(note or "").strip()]
            if progress is not None:
                normalized_progress = self._clamp_progress(progress)
                if normalized_progress is not None:
                    item["progress"] = normalized_progress
            elif status is not None:
                fallback_progress = self._fallback_progress(stage, item.get("status"), item.get("progress"))
                if fallback_progress is not None:
                    item["progress"] = fallback_progress
            job["updatedAt"] = time.time()

    def complete(self, job_id: str, result: Dict[str, Any], headline: Optional[str] = None) -> None:
        summary = {}
        details = result.get("details")
        if isinstance(details, dict) and isinstance(details.get("progress_summary"), dict):
            summary = details.get("progress_summary") or {}

        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["status"] = "completed"
            job["headline"] = str(headline or summary.get("headline") or "判卷已完成").strip() or "判卷已完成"
            items = summary.get("items")
            if isinstance(items, list) and items:
                job["items"] = copy.deepcopy(items)
            job["result"] = copy.deepcopy(result)
            job["error"] = ""
            job["updatedAt"] = time.time()

    def fail(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["status"] = "failed"
            job["headline"] = "判卷失败"
            job["error"] = str(message or "未知错误").strip() or "未知错误"
            job["updatedAt"] = time.time()
            items = job.setdefault("items", [])
            items.append(
                {
                    "stage": "failed",
                    "label": "处理失败",
                    "detail": job["error"],
                    "status": "failed",
                    "notes": ["本次请求未能完成，请检查模型服务或稍后重试。"],
                }
            )

    def snapshot(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            return copy.deepcopy(job)

    def _prune(self) -> None:
        cutoff = time.time() - float(self.ttl_sec)
        with self._lock:
            expired = [job_id for job_id, job in self._jobs.items() if float(job.get("updatedAt") or 0.0) < cutoff]
            for job_id in expired:
                self._jobs.pop(job_id, None)
