from pathlib import Path
from typing import Dict

class PromptLoader:
    def __init__(self, prompt_dir: str = "src/prompts/versions"):
        self.prompt_dir = Path(prompt_dir)
    
    def load(self, version: str, **kwargs) -> str:
        """
        加载指定版本的提示词，并填充变量
        :param version: 提示词文件名（不含扩展名），如 "v1_basic_grader"
        :param kwargs: 模板变量
        :return: 填充后的提示词字符串
        """
        file_path = self.prompt_dir / f"{version}.txt"
        if not file_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {file_path}")
            
        template = file_path.read_text(encoding="utf-8")
        
        # 简单的字符串替换，也可以换成 Jinja2
        for k, v in kwargs.items():
            template = template.replace(f"{{{{{k}}}}}", str(v))
            
        return template
