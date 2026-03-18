import requests
import json
import math
import hashlib
import re
import time

class LLMClient:
    def __init__(self, config=None):
        """
        Initialize with a config dict containing api_key, base_url, model_name
        """
        config = config or {}
        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url", "https://api.openai.com/v1")
        self.model = config.get("model_name", "gpt-3.5-turbo")
        self.embedding_model = config.get("embedding_model", self.model)
        self.embedding_max_batch = config.get("embedding_max_batch")
        self.demo_answer = config.get("demo_answer", "").strip()
        self._runtime_embedding_batch_limit = {}
        self._logged_embedding_batch_limits = set()

    def _demo_reply(self, content: str):
        return {
            "choices": [{
                "message": {
                    "content": content
                }
            }]
        }

    def _demo_grade_json(self):
        return json.dumps({
            "correct": False,
            "score": 0,
            "reason": f"API Key Missing for model {self.model}. Configure settings.yaml or environment variables."
        })

    def _demo_solve_text(self):
        if self.demo_answer:
            return self.demo_answer
        return f"[Demo] API Key Missing for model {self.model}. Please configure settings.yaml."

    def _expects_json(self, messages) -> bool:
        for msg in messages:
            content = (msg.get("content") or "")
            if "json" in content.lower():
                return True
        return False

    def chat_completion(self, messages, temperature=0.7, tools=None, tool_map=None, max_tool_rounds=3):
        started_at = time.perf_counter()
        perf = {
            "timing_ms": 0.0,
            "tool_rounds": 0,
            "tool_call_count": 0,
            "llm_round_timings_ms": [],
        }
        tool_trace = []
        if not self.api_key:
            # Fallback mock for demo if no API key
            wants_json = self._expects_json(messages)
            content = self._demo_grade_json() if wants_json else self._demo_solve_text()
            data = self._demo_reply(content)
            perf["timing_ms"] = round((time.perf_counter() - started_at) * 1000.0, 2)
            data["_perf"] = perf
            data["_tool_trace"] = tool_trace
            return data

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Copy messages to avoid modifying original list in place
        current_messages = list(messages)
        
        for _ in range(max_tool_rounds + 1):
            payload = {
                "model": self.model,
                "messages": current_messages,
                "temperature": temperature,
            }
            
            # Try with JSON mode first if no tools (assuming prompt asks for JSON)
            # But if it fails (e.g. prompt doesn't have "json"), fallback to normal text
            use_json_mode = False
            if not tools:
                # Check if we should enforce JSON mode. 
                # For now, let's try to enforce it, but handle 400 error.
                payload["response_format"] = {"type": "json_object"}
                use_json_mode = True
            else:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"

            try:
                url = f"{self.base_url.rstrip('/')}/chat/completions"
                llm_started_at = time.perf_counter()
                resp = requests.post(url, headers=headers, json=payload, timeout=60)
                
                # If 400 and we used JSON mode, try again without it
                if resp.status_code == 400 and use_json_mode:
                    print(f"LLM API 400 Error with JSON mode. Retrying without response_format...")
                    del payload["response_format"]
                    resp = requests.post(url, headers=headers, json=payload, timeout=60)
                perf["llm_round_timings_ms"].append(round((time.perf_counter() - llm_started_at) * 1000.0, 2))
                
                if resp.status_code != 200:
                    print(f"LLM API Error: {resp.status_code} - {resp.text}")
                    
                resp.raise_for_status()
                data = resp.json()
                
                choice = data['choices'][0]
                message = choice['message']
                
                # Check for tool calls
                if message.get('tool_calls'):
                    perf["tool_rounds"] = int(perf["tool_rounds"]) + 1
                    # Append assistant message with tool calls
                    current_messages.append(message)
                    
                    for tool_call in message['tool_calls']:
                        fn_name = tool_call['function']['name']
                        fn_args = json.loads(tool_call['function']['arguments'])
                        
                        # Execute tool
                        tool_started_at = time.perf_counter()
                        if tool_map and fn_name in tool_map:
                            print(f"[Tool] Calling {fn_name}({fn_args})")
                            tool_result = tool_map[fn_name](**fn_args)
                        else:
                            tool_result = f"Error: Tool {fn_name} not found"
                        perf["tool_call_count"] = int(perf["tool_call_count"]) + 1
                        tool_trace.append({
                            "name": fn_name,
                            "args": fn_args,
                            "result": str(tool_result)[:300],
                            "timing_ms": round((time.perf_counter() - tool_started_at) * 1000.0, 2),
                        })
                            
                        # Append tool result
                        current_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call['id'],
                            "content": str(tool_result)
                        })
                    # Loop continues to send tool results back to LLM
                else:
                    # Final response (no more tools)
                    perf["timing_ms"] = round((time.perf_counter() - started_at) * 1000.0, 2)
                    data["_perf"] = perf
                    data["_tool_trace"] = tool_trace
                    return data

            except Exception as e:
                print(f"LLM Call Error ({self.model}): {e}")
                data = {
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
                perf["timing_ms"] = round((time.perf_counter() - started_at) * 1000.0, 2)
                data["_perf"] = perf
                data["_tool_trace"] = tool_trace
                return data
        
        # If loop finishes without returning (max rounds reached)
        perf["timing_ms"] = round((time.perf_counter() - started_at) * 1000.0, 2)
        data["_perf"] = perf
        data["_tool_trace"] = tool_trace
        return data

    def _hash_embedding(self, text: str, dim: int = 256):
        """
        Deterministic local fallback embedding if remote embeddings are unavailable.
        """
        vec = [0.0] * dim
        s = (text or "").strip().lower()
        if not s:
            return vec
        for token in s.split():
            h = int(hashlib.md5(token.encode("utf-8", errors="ignore")).hexdigest()[:8], 16)
            idx = h % dim
            sign = 1.0 if (h % 2 == 0) else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embeddings(self, texts, model=None):
        """
        Return embeddings for a list of strings using OpenAI-compatible embeddings endpoint.
        """
        if isinstance(texts, str):
            texts = [texts]
        texts = [str(t or "") for t in texts]
        if not texts:
            return []

        if not self.api_key:
            return [self._hash_embedding(t) for t in texts]

        emb_model = model or self.embedding_model or self.model
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": emb_model,
            "input": texts
        }

        configured_limit = self.embedding_max_batch
        if configured_limit is not None:
            try:
                configured_limit = max(1, int(configured_limit))
            except Exception:
                configured_limit = None

        runtime_limit = self._runtime_embedding_batch_limit.get(emb_model)
        effective_limit = runtime_limit or configured_limit
        if effective_limit and len(texts) > effective_limit:
            out = []
            for i in range(0, len(texts), effective_limit):
                out.extend(self.embeddings(texts[i:i + effective_limit], model=emb_model))
            return out

        try:
            url = f"{self.base_url.rstrip('/')}/embeddings"
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            if resp.status_code != 200:
                # Some providers enforce strict per-call embedding batch size.
                if len(texts) > 1:
                    m = re.search(r"not be larger than\s*(\d+)", resp.text or "", flags=re.IGNORECASE)
                    if m:
                        limit = max(1, int(m.group(1)))
                        self._runtime_embedding_batch_limit[emb_model] = limit
                        if emb_model not in self._logged_embedding_batch_limits:
                            print(f"Embedding batch limit detected for {emb_model}: {limit}. Retrying with split batches.")
                            self._logged_embedding_batch_limits.add(emb_model)
                        out = []
                        for i in range(0, len(texts), limit):
                            out.extend(self.embeddings(texts[i:i + limit], model=emb_model))
                        return out
                print(f"Embedding API Error: {resp.status_code} - {resp.text}")
                return [self._hash_embedding(t) for t in texts]
            data = resp.json()
            rows = data.get("data", [])
            if not rows:
                return [self._hash_embedding(t) for t in texts]
            # Preserve input order by index.
            rows_sorted = sorted(rows, key=lambda x: x.get("index", 0))
            return [r.get("embedding", []) for r in rows_sorted]
        except Exception as e:
            print(f"Embedding Call Error ({emb_model}): {e}")
            return [self._hash_embedding(t) for t in texts]
