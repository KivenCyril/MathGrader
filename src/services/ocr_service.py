from abc import ABC, abstractmethod
import time
import logging
import requests
import base64

logger = logging.getLogger(__name__)

class OCRStrategy(ABC):
    """
    Abstract base class for OCR strategies.
    """
    name = "ocr"

    @abstractmethod
    def recognize(self, image_bytes: bytes, file_name: str = "", content_type: str = "") -> str:
        pass


def _is_aistudio_app_url(url: str) -> bool:
    value = str(url or "").strip().lower()
    return "aistudio-app.com" in value


def _infer_file_type(file_name: str, content_type: str) -> int:
    name = str(file_name or "").strip().lower()
    mime = str(content_type or "").strip().lower()
    if name.endswith(".pdf") or mime == "application/pdf":
        return 0
    return 1

class EasyOCRStrategy(OCRStrategy):
    """
    OCR strategy using the EasyOCR library.
    """
    name = "easyocr"

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

    def recognize(self, image_bytes: bytes, file_name: str = "", content_type: str = "") -> str:
        if not self.available or not self.reader:
            raise ImportError("EasyOCR is not available.")
        
        try:
            # detail=0 returns only the text
            result = self.reader.readtext(image_bytes, detail=0)
            return " ".join(result)
        except Exception as e:
            logger.error(f"EasyOCR recognition failed: {e}")
            raise e

class LocalPaddleOCRStrategy(OCRStrategy):
    """
    OCR strategy using local PaddleOCR.
    """
    name = "paddle_local"

    def __init__(self, use_angle_cls: bool = True, lang: str = "ch"):
        self.available = False
        self.reader = None
        self.use_angle_cls = bool(use_angle_cls)
        self.lang = str(lang or "ch").strip() or "ch"
        try:
            from paddleocr import PaddleOCR

            logger.info(
                "Initializing local PaddleOCR (use_angle_cls=%s, lang=%s)...",
                self.use_angle_cls,
                self.lang,
            )
            self.reader = PaddleOCR(use_angle_cls=self.use_angle_cls, lang=self.lang)
            self.available = True
            logger.info("Local PaddleOCR initialized successfully.")
        except ImportError:
            logger.warning("paddleocr not found. Install with `pip install paddleocr paddlepaddle`.")
        except Exception as e:
            logger.error(f"Failed to initialize local PaddleOCR: {e}")

    def recognize(self, image_bytes: bytes, file_name: str = "", content_type: str = "") -> str:
        if not self.available or not self.reader:
            raise ImportError("Local PaddleOCR is not available.")

        try:
            import cv2
            import numpy as np

            image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError("Failed to decode image bytes for PaddleOCR.")

            rows = self.reader.ocr(image, cls=self.use_angle_cls) or []
            parts = []
            for row in rows:
                for item in row or []:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        info = item[1]
                        if isinstance(info, (list, tuple)) and info:
                            parts.append(str(info[0]))
            return "\n".join([part for part in parts if part.strip()]).strip()
        except Exception as e:
            logger.error(f"Local PaddleOCR recognition failed: {e}")
            raise e


class AistudioAppOCRStrategy(OCRStrategy):
    """
    OCR strategy using AI Studio app endpoints such as https://*.aistudio-app.com/layout-parsing.
    """
    name = "baidu_aistudio_app"

    def __init__(self, token: str, url: str):
        self.token = str(token or "").strip()
        self.url = str(url or "").strip()
        if not self.token:
            logger.warning("AI Studio app token is missing.")
        if not self.url:
            logger.warning("AI Studio app URL is missing.")

    def recognize(self, image_bytes: bytes, file_name: str = "", content_type: str = "") -> str:
        if not self.token:
            raise ValueError("AI Studio app token is required.")
        if not self.url:
            raise ValueError("AI Studio app URL is required.")

        payload = {
            "file": base64.b64encode(image_bytes).decode("ascii"),
            "fileType": _infer_file_type(file_name, content_type),
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useChartRecognition": False,
        }
        headers = {
            "Authorization": f"token {self.token}",
            "Content-Type": "application/json",
        }
        response = requests.post(self.url, json=payload, headers=headers, timeout=90)
        response.raise_for_status()
        body = response.json()
        result = body.get("result") if isinstance(body, dict) else None
        if not isinstance(result, dict):
            raise ValueError(f"Unexpected AI Studio OCR response: {body}")

        layout_results = result.get("layoutParsingResults")
        if isinstance(layout_results, list):
            parts = []
            for item in layout_results:
                if not isinstance(item, dict):
                    continue
                markdown = item.get("markdown")
                if isinstance(markdown, dict):
                    text = str(markdown.get("text") or "").strip()
                    if text:
                        parts.append(text)
            if parts:
                return "\n\n".join(parts).strip()

        for key in ("text", "markdown", "content"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        raise ValueError(f"AI Studio OCR returned no readable text: {body}")


class BaiduOCRStrategy(OCRStrategy):
    """
    OCR strategy using Baidu OCR HTTP API.
    """
    name = "baidu_openapi"

    def __init__(self, access_token: str = None, api_key: str = None, secret_key: str = None, url: str = None):
        self.static_access_token = str(access_token or "").strip()
        self.api_key = str(api_key or "").strip()
        self.secret_key = str(secret_key or "").strip()
        self.access_token = ""
        self._token_expires_at = 0.0
        self.url = str(url or "https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic").strip()
        self.token_url = "https://aip.baidubce.com/oauth/2.0/token"
        
        if not self.static_access_token and not self.api_key:
             logger.warning("Baidu OCR credential is missing.")

    def _ensure_access_token(self) -> str:
        now = time.time()
        if self.static_access_token:
            return self.static_access_token
        if self.access_token and now < self._token_expires_at:
            return self.access_token

        if not self.api_key or not self.secret_key:
            raise ValueError("Baidu OCR requires OCR access_token or OCR api_key + secret_key.")

        params = {
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.secret_key,
        }
        response = requests.post(self.token_url, params=params, timeout=20)
        response.raise_for_status()
        result = response.json()
        token = str(result.get("access_token") or "").strip()
        if not token:
            raise ValueError(f"Failed to fetch Baidu OCR access token: {result}")

        expires_in = int(result.get("expires_in") or 2592000)
        self.access_token = token
        self._token_expires_at = now + max(60, expires_in - 300)
        return self.access_token

    def recognize(self, image_bytes: bytes, file_name: str = "", content_type: str = "") -> str:
        access_token = self._ensure_access_token()

        try:
            # Baidu OCR requires Base64 encoded image
            img_b64 = base64.b64encode(image_bytes).decode('utf-8')
            
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            params = {'access_token': access_token}
            data = {'image': img_b64}
            
            response = requests.post(self.url, params=params, data=data, headers=headers, timeout=20)
            response.raise_for_status()
            result = response.json()
            
            if 'words_result' in result:
                text = " ".join([item['words'] for item in result['words_result']])
                return text
            elif 'error_msg' in result:
                raise Exception(f"Baidu OCR API Error: {result['error_msg']}")
            else:
                return str(result)
                
        except Exception as e:
            logger.error(f"Baidu OCR recognition failed: {e}")
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
            strategy = LocalPaddleOCRStrategy()
            if not strategy.available:
                raise ValueError("Local PaddleOCR is explicitly requested but not available.")
            return strategy
        elif strategy_name == "baidu":
            from src.services.config_service import config_service
            paddle_config = config_service.config.get('ocr', {}).get('paddle', {})
            url = paddle_config.get('url')
            if _is_aistudio_app_url(url):
                token = paddle_config.get('token') or paddle_config.get('access_token') or paddle_config.get('api_key')
                return AistudioAppOCRStrategy(token=token, url=url)
            return BaiduOCRStrategy(
                access_token=paddle_config.get('access_token'),
                api_key=paddle_config.get('api_key'),
                secret_key=paddle_config.get('secret_key'),
                url=url,
            )
        elif strategy_name == "easyocr":
            strategy = EasyOCRStrategy()
            if not strategy.available:
                raise ValueError("EasyOCR is explicitly requested but not available.")
            return strategy
        elif strategy_name == "mock":
            return MockOCRStrategy()
        elif strategy_name == "auto":
            # Prefer configured Baidu OCR backend if available.
            try:
                from src.services.config_service import config_service
                paddle_config = config_service.config.get('ocr', {}).get('paddle', {})
                url = paddle_config.get('url')
                if _is_aistudio_app_url(url):
                    token = paddle_config.get('token') or paddle_config.get('access_token') or paddle_config.get('api_key')
                    if token:
                        logger.info("Using AI Studio app OCR backend: %s", url)
                        return AistudioAppOCRStrategy(token=token, url=url)
                    logger.warning("AI Studio app OCR URL is configured but token/access_token/api_key is missing.")
                else:
                    has_baidu_credentials = bool(
                        paddle_config.get('access_token') or (
                            paddle_config.get('api_key') and paddle_config.get('secret_key')
                        )
                    )
                    if has_baidu_credentials:
                        logger.info("Using Baidu OCR OpenAPI backend.")
                        return BaiduOCRStrategy(
                            access_token=paddle_config.get('access_token'),
                            api_key=paddle_config.get('api_key'),
                            secret_key=paddle_config.get('secret_key'),
                            url=url,
                        )
                    if paddle_config.get('api_key') and not paddle_config.get('secret_key') and not paddle_config.get('access_token'):
                        logger.warning(
                            "Ignoring incomplete Baidu OCR OpenAPI config: api_key is present but secret_key/access_token is missing."
                        )
            except Exception as e:
                logger.warning(f"Failed to initialize Baidu OCR API, falling back to local OCR: {e}")

            # Fallback to local PaddleOCR.
            strategy = LocalPaddleOCRStrategy()
            if strategy.available:
                logger.info("Baidu OCR API unavailable, falling back to local PaddleOCR.")
                return strategy

            # Last local fallback: EasyOCR.
            strategy = EasyOCRStrategy()
            if strategy.available:
                logger.info("Local PaddleOCR not available, falling back to EasyOCR.")
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
        
        return self.strategy.recognize(
            image_bytes,
            file_name=getattr(image_file, "filename", "") or "",
            content_type=getattr(image_file, "content_type", "") or "",
        )
