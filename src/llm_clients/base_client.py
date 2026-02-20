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

    def chat_completion(self, messages, temperature=0.7, tools=None, tool_map=None, max_tool_rounds=3):
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
        
        # Copy messages to avoid modifying original list in place
        current_messages = list(messages)
        
        for _ in range(max_tool_rounds + 1):
            payload = {
                "model": self.model,
                "messages": current_messages,
                "temperature": temperature,
            }
            
            # Only enable JSON mode if no tools are pending (or if we want final JSON)
            # Strategy: If tools provided, don't force JSON object yet, let model decide.
            # But our prompt usually asks for JSON. This is tricky.
            # Most robust way: If tools enabled, disable response_format, 
            # and rely on prompt instruction for final JSON.
            if not tools:
                payload["response_format"] = {"type": "json_object"}
            else:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"

            try:
                url = f"{self.base_url.rstrip('/')}/chat/completions"
                resp = requests.post(url, headers=headers, json=payload, timeout=60)
                
                if resp.status_code != 200:
                    print(f"LLM API Error: {resp.status_code} - {resp.text}")
                    
                resp.raise_for_status()
                data = resp.json()
                
                choice = data['choices'][0]
                message = choice['message']
                
                # Check for tool calls
                if message.get('tool_calls'):
                    # Append assistant message with tool calls
                    current_messages.append(message)
                    
                    for tool_call in message['tool_calls']:
                        fn_name = tool_call['function']['name']
                        fn_args = json.loads(tool_call['function']['arguments'])
                        
                        # Execute tool
                        if tool_map and fn_name in tool_map:
                            print(f"[Tool] Calling {fn_name}({fn_args})")
                            tool_result = tool_map[fn_name](**fn_args)
                        else:
                            tool_result = f"Error: Tool {fn_name} not found"
                            
                        # Append tool result
                        current_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call['id'],
                            "content": str(tool_result)
                        })
                    # Loop continues to send tool results back to LLM
                else:
                    # Final response (no more tools)
                    return data

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
        
        # If loop finishes without returning (max rounds reached)
        return data
