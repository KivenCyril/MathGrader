import requests
import json
import os

class LLMClient:
    def __init__(self, config=None):
        """
        Initialize with a config dict containing api_key, base_url, model_name
        """
        config = config or {}
        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url", "https://api.openai.com/v1")
        self.model = config.get("model_name", "gpt-3.5-turbo")

    def chat_completion(self, messages, temperature=0.7):
        if not self.api_key:
             # Fallback mock for demo if no API key
            return {
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "correct": False,
                            "score": 0,
                            "reason": f"API Key Missing for model {self.model}. Please check settings.yaml."
                        })
                    }
                }]
            }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"}
        }
        
        try:
            # print(f"Sending request to {self.base_url}/chat/completions")
            resp = requests.post(f"{self.base_url}/chat/completions", headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"LLM Call Error ({self.model}): {e}")
            return {
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "correct": False,
                            "score": 0,
                            "reason": f"LLM Error ({self.model}): {str(e)}"
                        })
                    }
                }]
            }
