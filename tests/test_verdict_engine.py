import unittest

from src.grading.verdict_engine import VerdictEngine


class _FakeRubricLoader:
    def load(self, question_type, rubric_override=None, rubric_text=None):
        return {"question_type": question_type, "source": "fake"}

    def prompt_text(self, rubric):
        return "rubric prompt"

    def notes(self, rubric):
        return ["rubric note"]


class _FakeEngine:
    def __init__(self):
        self.method_id = "fake_method"
        self.recommender = type("Recommender", (), {"enabled": True})()
        self.rubric_loader = _FakeRubricLoader()
        self.default_tools_enabled = True
        self.config = {}

    def _normalize_question_type(self, value):
        return str(value or "").strip().lower()

    def _classify_question_type(self, question, truth, student):
        return "choice"

    def _elapsed_ms(self, started_at):
        return 12.34

    def _answers_equivalent(self, truth, student):
        return False

    def _try_rule_based_choice_grade(self, truth, student, safe_max, trace_id, total_started_at, equivalence_started_at):
        return {
            "correct": True,
            "reason": "rule",
            "methodUsed": "fake_method_rule_fast_path",
            "similarQuestions": [],
            "retrieval": {
                "enabled": True,
                "strategy": "skipped_rule_fast_path",
                "datasetId": None,
                "matched": 0,
            },
            "details": {},
        }


class VerdictEngineTests(unittest.TestCase):
    def test_choice_rule_fast_path_keeps_metadata_shape(self):
        engine = _FakeEngine()
        verdict_engine = VerdictEngine(engine)
        progress_events = []

        result = verdict_engine.evaluate(
            question="1+1=?",
            truth="A",
            student="A",
            max_score=5,
            dataset_id="demo.jsonl",
            question_type="choice",
            trace_id="trace-1",
            progress_callback=progress_events.append,
        )

        self.assertTrue(result["correct"])
        self.assertEqual(result["retrieval"]["datasetId"], "demo.jsonl")
        self.assertEqual(result["details"]["rubric"], {"question_type": "choice", "source": "fake"})
        self.assertEqual(
            result["details"]["scoring_request"],
            {"need_score": True, "requested_mode": "auto"},
        )
        self.assertEqual(result["details"]["progress_summary"]["headline"], "判卷已完成")
        self.assertEqual(result["details"]["progress_summary"]["items"][0]["stage"], "rule_fast_path")
        self.assertEqual(progress_events[-1]["stage"], "rule_fast_path")


if __name__ == "__main__":
    unittest.main()
