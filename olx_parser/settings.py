import os
import pathlib
from typing import Any
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()


class BaseConfig:
    BASE_DIR: pathlib.Path = pathlib.Path(__file__).parent
    TEST = False
    PROXY_SELLER_KEY: str = os.getenv("PROXY_SELLER_KEY", "")

    HEADERS = {
        'User-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36'
    }

    # api olx link params:
    # OLX_OFFSET: 0 - 1000
    # OLX_CATEGORIES: from ALLOWED_CATEGORIES
    # OLX_CITY: city_id
    # OLX_OWNER_TYPE: # business \ private
    # OLX_SORT: filter_float_price%3Aasc \  created_at%3Adesc
    # OLX_START_PRICE: 0 \ 99999999
    # OLX_CURRENCY: UAH \ USD
    OLX_API_BASE_LINK = 'https://www.olx.ua/api/v1/offers/?offset=OLX_OFFSET&limit=50&category_id=OLX_CATEGORIES&city_id=OLX_CITY&owner_type=OLX_OWNER_TYPE&currency=OLX_CURRENCY&sort_by=OLX_SORT&filter_float_price%3Afrom=OLX_START_PRICE&filter_refiners=spell_checker&facets=%5B%7B%22field%22%3A%22district%22%2C%22fetchLabel%22%3Atrue%2C%22fetchUrl%22%3Atrue%2C%22limit%22%3A30%7D%5D'

    ALLOWED_CATEGORIES = {
        1758: 'Продаж квартир',
        1760: 'Оренда квартир',

        330: 'Оренда дома',
        1602: 'Продаж дома',

        20: 'Оренда земля',
        1608: 'Продаж земля',

        1614: 'Оренда комерція',
        1612: 'Продаж комерція',

        28: 'Оренда гаражі, парковки',
        21: 'Продаж гаражі, парковки',

        1755: 'Продаж кімнат',
        1756: 'Оренда кімнат',

    }

    SLUG_TYPE_OBJ = {
        'Продаж кімнат': 'room',
        'Оренда кімнат': 'room',
        'Продаж квартир': 'apartment',
        'Оренда квартир': 'apartment',
        'Оренда дома': 'house',
        'Продаж дома': 'house',
        'Оренда земля': 'land',
        'Продаж земля': 'land',
        'Оренда комерція': 'commercial',
        'Продаж комерція': 'commercial',
        'Оренда гаражі, парковки': 'garage',
        'Продаж гаражі, парковки': 'garage',
    }


    API_HOST: str = os.getenv("API_HOST", "")
    API_TOKEN: str = os.getenv("API_TOKEN", "")

    DATABASE_USER: str = os.getenv("DATABASE_USER", "root")
    DATABASE_PASSWORD: str = os.getenv("DATABASE_PASSWORD", "root")
    DATABASE_HOST: str = os.getenv("DATABASE_HOST", "mysql")
    DATABASE_NAME: str = os.getenv("DATABASE_NAME", "db")
    DATABASE_PORT: int = os.getenv("DATABASE_PORT", 3306)

    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "token")

    # openAI tokens
    PROMPT_ID: str = os.getenv("PROMPT_ID", "")
    PROMPT_VERSION: str = os.getenv("PROMPT_VERSION", "")
    OPEN_AI_TOKEN: str = os.getenv("OPEN_AI_TOKEN", "token")

    AGENT_JK_ID: str = os.getenv("AGENT_JK_ID", None)
    AGENT_OWNER_ID: str = os.getenv("AGENT_OWNER_ID", None)

    PROXY: str = os.getenv("PROXY", None)

    # DATABASE_URL = f'mysql+pymysql://{DATABASE_USER}:{DATABASE_PASSWORD}@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}'
    VECTOR_API_URL: str = os.getenv("VECTOR_API_URL", "http://108.61.170.97/api/v1/task/")
    PHONE_API_URL: str = os.getenv("PHONE_API_URL", "http://0.0.0.0:2754/api/v1/tasks/")

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
