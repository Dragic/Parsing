import os
import pathlib
from typing import Any
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()


class BaseConfig:
    BASE_DIR: pathlib.Path = pathlib.Path(__file__).parent

    HEADERS = {
        'User-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
        'Priority': '',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7,uk;q=0.6',
        'Authority': 'dom.ria.com',
    }

    RIA_OBJ_URL = {
        'rent': {
            'apartment': [
                'https://dom.ria.com/uk/search/?excludeSold=1&category=1&realty_type=2&operation=3&state_id=RIA_STATE_ID&price_cur=1&wo_dupl=1&sort=created_at&period=per_allday&photos_count_from=3&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&ch=246_244'
            ],
            'house': [
                'https://dom.ria.com/uk/search/?excludeSold=1&category=4&realty_type=0&operation=3&state_id=RIA_STATE_ID&price_cur=1&wo_dupl=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&ch=246_244'
            ],
            'commercial': [
                'https://dom.ria.com/uk/search/?excludeSold=1&category=13&realty_type=0&operation=3&state_id=RIA_STATE_ID&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&ch=242_240,247_252'
            ],
            'room': [
                'https://dom.ria.com/uk/search/?excludeSold=1&category=40&realty_type=0&operation=3&state_id=RIA_STATE_ID&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&ch=226_223,242_239,247_252'
            ],
            'garage': [
                'https://dom.ria.com/uk/search/?excludeSold=1&category=30&realty_type=0&operation=3&state_id=RIA_STATE_ID&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&ch=226_223,242_239,247_252'
            ]
        },
        'sale': {
            'apartment': [
                'https://dom.ria.com/uk/search/?excludeSold=1&category=1&realty_type=2&operation=1&state_id=RIA_STATE_ID&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&wo_dupl=1&ch=242_239,247_252'
            ],
            'house': [
                'https://dom.ria.com/uk/search/?excludeSold=1&category=4&realty_type=0&operation=1&state_id=RIA_STATE_ID&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&wo_dupl=1&ch=226_223,242_239,247_252'
            ],
            'land': [
                'https://dom.ria.com/uk/search/?excludeSold=1&category=24&realty_type=0&operation=1&state_id=RIA_STATE_ID&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&ch=226_223,242_239,251_248'
            ],
            'commercial': [
                'https://dom.ria.com/uk/search/?excludeSold=1&category=13&realty_type=0&operation=1&state_id=RIA_STATE_ID&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&ch=226_223,242_239,247_252'
            ],
            'room': [
                'https://dom.ria.com/uk/search/?excludeSold=1&category=40&realty_type=0&operation=1&state_id=RIA_STATE_ID&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&ch=226_223,242_239,247_252'
            ],
            'garage': [
                'https://dom.ria.com/uk/search/?excludeSold=1&category=30&realty_type=0&operation=1&state_id=RIA_STATE_ID&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&ch=226_223,242_239,247_252'
            ]
        }
    }

    DATABASE_USER: str = os.getenv("DATABASE_USER", "root")
    DATABASE_PASSWORD: str = os.getenv("DATABASE_PASSWORD", "root")
    DATABASE_HOST: str = os.getenv("DATABASE_HOST", "mysql")
    DATABASE_NAME: str = os.getenv("DATABASE_NAME", "db")
    DATABASE_PORT: int = os.getenv("DATABASE_PORT", 3306)

    PROMPT_ID: str = os.getenv("PROMPT_ID", "")
    PROMPT_VERSION: str = os.getenv("PROMPT_VERSION", "")
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
    DATABASE_USER = "test_user"
    DATABASE_PASSWORD = "db_password"
    DATABASE_HOST = 'mysql'
    DATABASE_NAME = 'test_db'
    DATABASE_PORT = 3306
    BASE_DIR: pathlib.Path = pathlib.Path(__file__).parent
    DATABASE_URL = f'mysql+pymysql://test_user:db_password@mysql:3306/test_db'


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
