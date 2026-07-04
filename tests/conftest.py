"""Configuración compartida de pytest.

Se definen variables de entorno dummy antes de que ningún test importe
módulos del proyecto, para que los getters perezosos de `config.py` no
fallen al ejecutarse durante los tests.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("UPSTASH_REDIS_REST_URL", "https://test.upstash.io")
os.environ.setdefault("UPSTASH_REDIS_REST_TOKEN", "test-upstash-token")
os.environ.setdefault("GMAIL_OAUTH_TOKEN_JSON", '{"refresh_token": "test"}')
os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-telegram-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "123456")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
