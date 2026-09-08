import os
import pathlib
from typing import Any
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()


class BaseConfig:
    BASE_DIR: pathlib.Path = pathlib.Path(__file__).parent
    TEST = False
    HEADERS = {
        'User-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36'
    }

    DATABASE_USER: str = os.getenv("DATABASE_USER", "root")
    DATABASE_PASSWORD: str = os.getenv("DATABASE_PASSWORD", "root")
    DATABASE_HOST: str = os.getenv("DATABASE_HOST", "mysql")
    DATABASE_NAME: str = os.getenv("DATABASE_NAME", "db")
    DATABASE_PORT: int = os.getenv("DATABASE_PORT", 3306)

    # openAI token - required by ai_repair.py
    OPEN_AI_TOKEN: str = os.getenv("OPEN_AI_TOKEN", "token")

    VECTOR_API_URL: str = os.getenv("VECTOR_API_URL", "http://108.61.170.97/api/v1/task/")

    DATABASE_URL = f'postgresql+psycopg2://{DATABASE_USER}:{DATABASE_PASSWORD}@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}'
    DATABASE_CONNECT_DICT: dict[str, Any] = {}

    UPDATE_ADS: bool = False if os.getenv("UPDATE_ADS", None) == 'false' else True


class DevelopmentConfig(BaseConfig):
    pass


class ProductionConfig(BaseConfig):
    pass


class TestingConfig(BaseConfig):
    TEST = True
    DATABASE_USER = "test_user"
    DATABASE_PASSWORD = "db_password"
    DATABASE_HOST = 'mysql'
    DATABASE_NAME = 'test_db'
    DATABASE_PORT = 3306
    BASE_DIR: pathlib.Path = pathlib.Path(__file__).parent
    DATABASE_URL = "sqlite:///test.db"


@lru_cache()
def get_settings():
    config_cls_dict = {
        "development": DevelopmentConfig,
        "production": ProductionConfig,
        "testing": TestingConfig,
    }

    config_name = os.getenv("ENVIRONMENT", "development").lower()
    config_cls = config_cls_dict[config_name]
    return config_cls()


settings = get_settings()
