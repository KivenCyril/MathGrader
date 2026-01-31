import yaml
import os
from pathlib import Path

class ConfigService:
    def __init__(self, config_path="settings.yaml"):
        self.config = self._load_config(config_path)

    def _load_config(self, path):
        p = Path(path)
        if not p.exists():
            # Fallback default
            return {
                "models": {},
                "roles": {"grader": "deepseek", "reviewer": "qwen"}
            }
        with open(p, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def get_model_config(self, model_alias):
        """
        Get config for a specific model alias (e.g. 'deepseek', 'qwen')
        """
        return self.config.get("models", {}).get(model_alias, {})

    def get_role_model(self, role):
        """
        Get the model alias assigned to a role (e.g. 'grader' -> 'deepseek')
        """
        return self.config.get("roles", {}).get(role)

# Global instance
config_service = ConfigService()
