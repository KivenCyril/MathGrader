from abc import ABC, abstractmethod
import logging
import requests
import base64

logger = logging.getLogger(__name__)

class OCRStrategy(ABC):
    """
    Abstract base class for OCR strategies.
    """
    @abstractmethod
    def recognize(self, image_bytes: bytes) -> str:
        pass

class EasyOCRStrategy(OCRStrategy):
    """
    OCR strategy using the EasyOCR library.
    """
    def __init__(self, gpu=False):
        self.available = False
        self.reader = None
        try:
            import easyocr
            # Initialize reader once
            logger.info(f"Initializing EasyOCR (gpu={gpu})...")
            self.reader = easyocr.Reader(['ch_sim', 'en'], gpu=gpu)
            self.available = True
            logger.info("EasyOCR initialized successfully.")
        except ImportError:
            logger.warning("EasyOCR not found. Install with `pip install easyocr`.")
        except Exception as e:
            logger.error(f"Failed to initialize EasyOCR: {e}")

    def recognize(self, image_bytes: bytes) -> str:
        if not self.available or not self.reader:
            raise ImportError("EasyOCR is not available.")
        
        try:
            # detail=0 returns only the text
            result = self.reader.readtext(image_bytes, detail=0)
            return " ".join(result)
        except Exception as e:
            logger.error(f"EasyOCR recognition failed: {e}")
            raise e

class PaddleOCRStrategy(OCRStrategy):
    """
    OCR strategy using Baidu PaddleOCR API.
    """
    def __init__(self, api_key: str = None, secret_key: str = None):
        self.access_token = api_key
        self.url = "https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic"
        
        if not self.access_token:
             logger.warning("PaddleOCR API key is missing.")

    def recognize(self, image_bytes: bytes) -> str:
        if not self.access_token:
            raise ValueError("PaddleOCR Access Token is missing.")

        try:
            # Baidu OCR requires Base64 encoded image
            img_b64 = base64.b64encode(image_bytes).decode('utf-8')
            
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            params = {'access_token': self.access_token}
            data = {'image': img_b64}
            
            response = requests.post(self.url, params=params, data=data, headers=headers)
            result = response.json()
            
            if 'words_result' in result:
                text = " ".join([item['words'] for item in result['words_result']])
                return text
            elif 'error_msg' in result:
                raise Exception(f"PaddleOCR API Error: {result['error_msg']}")
            else:
                return str(result)
                
        except Exception as e:
            logger.error(f"PaddleOCR recognition failed: {e}")
            raise e

class MockOCRStrategy(OCRStrategy):
    """
    Mock OCR strategy for testing or fallback.
    """
    def recognize(self, image_bytes: bytes) -> str:
        logger.info("Using Mock OCR strategy.")
        return "[Mock OCR] 识别结果：123.45 (请安装 easyocr 以启用真实识别)"

class OCRService:
    """
    Service to handle OCR operations using a specific strategy.
    """
    def __init__(self, strategy_name: str = "auto"):
        self.strategy = self._get_strategy(strategy_name)

    def _get_strategy(self, strategy_name: str) -> OCRStrategy:
        if strategy_name == "paddle":
            # Hardcoded for now based on user input, ideally load from config
            # In a real app, inject config_service here
            from src.services.config_service import config_service
            paddle_config = config_service.config.get('ocr', {}).get('paddle', {})
            api_key = paddle_config.get('api_key')
            return PaddleOCRStrategy(api_key=api_key)
        elif strategy_name == "easyocr":
            strategy = EasyOCRStrategy()
            if not strategy.available:
                raise ValueError("EasyOCR is explicitly requested but not available.")
            return strategy
        elif strategy_name == "mock":
            return MockOCRStrategy()
        elif strategy_name == "auto":
            # Try EasyOCR, fallback to Mock
            strategy = EasyOCRStrategy()
            if strategy.available:
                return strategy
            return MockOCRStrategy()
        else:
            raise ValueError(f"Unknown OCR strategy: {strategy_name}")

    def recognize(self, image_file) -> str:
        """
        Recognize text from an image file.
        
        Args:
            image_file: A file-like object (e.g. from Flask request.files)
            
        Returns:
            str: The recognized text.
        """
        # Read bytes from the file pointer
        # Note: This moves the file pointer to the end.
        image_bytes = image_file.read()
        
        # Reset file pointer in case it's needed again (optional but good practice)
        image_file.seek(0)
        
        return self.strategy.recognize(image_bytes)
