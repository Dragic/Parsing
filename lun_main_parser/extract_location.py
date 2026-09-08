import asyncio
import json
import os
import re

import aiohttp
from bs4 import BeautifulSoup

from config import headers
from settings import settings

OUTPUT_FILE = 'cities_regions.json'


def extract_json_from_push(text: str) -> dict:
    match = re.search(r'self\.__next_f\.push\(\[1,"(.+)"\]\)', text, re.DOTALL)
    if not match:
        return {}

    raw = match.group(1)

    # НЕ робити encode/decode unicode_escape — це ламає UTF-8
    # Просто екрануємо лапки назад і парсимо як JSON рядок
    raw = raw.replace('\\"', '"').replace('\\\\', '\\')

    json_match = re.search(r'\{.+\}', raw, re.DOTALL)
    if not json_match:
        return {}

    return json.loads(json_match.group(0))


def load_data() -> dict:
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}


def save_data(data: dict) -> None:
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_city_to_region(data: dict, region_name: str, city_geo_id: int, city_name: str) -> None:
    cities = data.setdefault(region_name, [])

    for city in cities:
        if city.get('geoId') == city_geo_id:
            return

    cities.append({'geoId': city_geo_id, 'name': city_name})


def process_geo_entities(geo_entities: list, data: dict) -> None:
    region_name = None
    city_geo_id = None
    city_name = None

    for geo in geo_entities:
        geo_type = geo.get('type')
        if geo_type == 'region':
            region_name = geo.get('name')
        elif geo_type == 'city':
            city_geo_id = geo.get('geoId')
            city_name = geo.get('name')

    if region_name and city_geo_id and city_name:
        add_city_to_region(data, region_name, city_geo_id, city_name)


PAGES_DEPTH = 100


def build_page_url(base_url: str, geo_id: int, page: int) -> str:
    return f'{base_url}?page={page}&geoDistance={geo_id}%3A1000000&sort=insert_time'


async def fetch_and_collect(session, url: str, data: dict) -> None:
    try:
        async with session.get(url=url, proxy=settings.PROXY, headers=headers) as response:
            text = await response.text()

        soup = BeautifulSoup(text, 'html.parser')
        scripts = soup.find_all('script')

        for script in scripts:
            if 'bankId' in script.text:
                page_data = extract_json_from_push(script.text)
                cards = page_data.get('realties', {}).get('cards')
                if not cards:
                    continue

                for card in cards:
                    geo_entities = card.get('geoEntities', [])
                    process_geo_entities(geo_entities, data)

    except Exception as ex:
        print(f'ПОМИЛКА ПАРСИНГУ {url} - {ex}')


async def task_watch() -> None:
    urls = [
        {
            'url': 'https://lun.ua/sale/kyiv/houses',
            'geoId': 10009580,
        },
        # {
        #     'url': 'https://lun.ua/sale/lviv/houses',
        #     'geoId': 10012684,
        # },
        # {
        #     'url': 'https://lun.ua/sale/odesa/houses',
        #     'geoId': 10016589,
        # },
        # {
        #     'url': 'https://lun.ua/sale/vinnytsia/houses',
        #     'geoId': 10003908,
        # },
        # {
        #     'url': 'https://lun.ua/sale/dnipro/houses',
        #     'geoId': 10006463,
        # },
        # {
        #     'url': 'https://lun.ua/sale/zhytomyr/houses',
        #     'geoId': 10007252,
        # },
        # {
        #     'url': 'https://lun.ua/sale/zp/houses',
        #     'geoId': 10007846,
        # },
        # {
        #     'url': 'https://lun.ua/sale/if/houses',
        #     'geoId': 10008717,
        # },
        # {
        #     'url': 'https://lun.ua/sale/kr/houses',
        #     'geoId': 10011240,
        # },
        # {
        #     'url': 'https://lun.ua/sale/volyn/houses',
        #     'geoId': 10012656,
        # },
        # {
        #     'url': 'https://lun.ua/sale/mykolaiv/houses',
        #     'geoId': 10013982,
        # },
        # {
        #     'url': 'https://lun.ua/sale/poltava/houses',
        #     'geoId': 10018885,
        # },
        # {
        #     'url': 'https://lun.ua/sale/rivne/houses',
        #     'geoId': 10019894,
        # },
        # {
        #     'url': 'https://lun.ua/sale/sumy/houses',
        #     'geoId': 10022820,
        # },
        # {
        #     'url': 'https://lun.ua/sale/ternopil/houses',
        #     'geoId': 10023304,
        # },
        # {
        #     'url': 'https://lun.ua/sale/uz/houses',
        #     'geoId': 10023968,
        # },
        # {
        #     'url': 'https://lun.ua/sale/kharkiv/houses',
        #     'geoId': 10024345,
        # },
        # {
        #     'url': 'https://lun.ua/sale/khmelnytskyi/houses',
        #     'geoId': 10024474,
        # },
        # {
        #     'url': 'https://lun.ua/sale/cherkasy/houses',
        #     'geoId': 10025145,
        # },
        # {
        #     'url': 'https://lun.ua/sale/chernivtsi/houses',
        #     'geoId': 10025207,
        # },
        # {
        #     'url': 'https://lun.ua/sale/chernihiv/houses',
        #     'geoId': 10025209,
        # },
    ]

    data = load_data()

    session = aiohttp.ClientSession()
    for obj_data in urls:
        base_url = obj_data.get('url')
        geo_id = obj_data.get('geoId')

        for page in range(1, PAGES_DEPTH + 1):
            page_url = build_page_url(base_url, geo_id, page)
            await fetch_and_collect(session=session, url=page_url, data=data)

    await session.close()

    save_data(data)
    print(f'Готово. Дані збережено у {OUTPUT_FILE}')


if __name__ == '__main__':
    asyncio.run(task_watch())