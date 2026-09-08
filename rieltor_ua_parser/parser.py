import asyncio
import logging
import time
import re
from collections import defaultdict

import aiohttp

from proxy_seller_user_api import Api
from urllib.parse import quote
import validate_addition_params
from settings import settings
from vector_service import api_send_task
import ai_repair
from bs4 import BeautifulSoup
from config import headers
import models
from currency_api import currency_converter
from log import logger
from database import db_session
from datetime import datetime, timedelta
import ai_agent
import location_api


# AI additions params recognize
SALE_AI_PROPERTIES_TYPE = ['apartment', 'house', 'commercial']
RENT_AI_PROPERTIES_TYPE = ['apartment', 'house', 'commercial']


logger_parser = logging.getLogger('log.rieltor_ua_parser.py')

kiev_metro_by_name = {
    'Академмістечко': 1,
    'Арсенальна': 2,
    'Берестейська': 3,
    'Вокзальна': 9,
    'Гідропарк': 11,
    'Дарниця': 13,
    'Дніпро': 55,
    'Житомирська': 16,
    'Лівобережна': 24,
    'Лісова': 25,
    'Нивки': 29,
    'Політехнічний інститут': 38,
    'Святошин': 41,
    'Театральна': 47,
    'Університет': 49,
    'Хрещатик': 51,
    'Чернігівська': 53,
    'Шулявська': 54,
    'Бориспільська': 4,
    'Видубичі': 6,
    'Вирлиця': 7,
    'Дорогожичі': 15,
    'Звіринецька': 17,
    'Золоті ворота': 18,
    'Кловська': 20,
    "Лук'янівська": 26,
    'Осокорки': 32,
    'Палац спорту': 33,
    'Печерська': 35,
    'Позняки': 37,
    'Сирець': 43,
    'Славутич': 45,
    'Харківська': 50,
    'Червоний хутір': 52,
    'Васильківська': 5,
    'Виставковий центр': 8,
    'Героїв Дніпра': 10,
    'Голосіївська': 12,
    'Деміївська': 14,
    'Іподром': 19,
    'Контрактова площа': 21,
    'Либідська': 23,
    'Майдан Незалежності': 27,
    'Мінська': 28,
    'Оболонь': 30,
    'Олімпійська': 31,
    'Палац Україна': 34,
    'Площа Українських Героїв': 36,
    'Почайна': 39,
    'Поштова площа': 40,
    'Тараса Шевченка': 46,
    'Теремки': 48,
}

REGIONS = [
    {"id": 10, "slug": "Київська-r111"},
    {"id": 5, "slug": "Львівська-r102"},
    {"id": 12, "slug": "Одеська-r113"},
    {"id": 7, "slug": "Харківська-r123"},
    {"id": 15, "slug": "Івано-Франківська-r104"},
    {"id": 11, "slug": "Дніпропетровська-r119"},
    {"id": 4, "slug": "Хмельницька-r108"},
    {"id": 22, "slug": "Закарпатська-r101"},
    {"id": 9, "slug": "Рівненська-r107"},
    {"id": 1, "slug": "Вінницька-r109"},
    {"id": 20, "slug": "Полтавська-r117"},
    {"id": 14, "slug": "Запорізька-r122"},
    {"id": 3, "slug": "Тернопільська-r105"},
    {"id": 8, "slug": "Сумська-r118"},
    {"id": 6, "slug": "Чернігівська-r116"},
    {"id": 19, "slug": "Миколаївська-r115"},
    {"id": 2, "slug": "Житомирська-r110"},
    {"id": 25, "slug": "Чернівецька-r10"},
    {"id": 24, "slug": "Черкаська-r112"},
    {"id": 16, "slug": "Кіровоградська-r114"},
    {"id": 18, "slug": "Волинська-r103"}
]

URLS = [
    ("sale", "apartment"),
    ("sale", "house"),
    ("sale", "commercial"),
    ("sale", "land"),
    ("rent", "apartment"),
    ("rent", "house"),
    ("rent", "commercial"),
]

TYPE_MAP = {
    "apartment": "flats",
    "house": "houses",
    "commercial": "commercial",
    "land": "lands",
}

ACTION_MAP = {
    "sale": "sale",
    "rent": "rent",
}

def district_pars(district):
    dict_district = {
        'Шевченківський': 15190,
        'Дніпровський': 15182,
        'Деснянський': 15183,
        'Святошинський': 15186,
        'Голосіївський': 15184,
        "Солом'янський": 15185,
        'Оболонський': 15187,
        'Печерський': 15189,
        'Подільський': 15188,
        'Дарницький': 15181,
    }
    for k, v in dict_district.items():
        if k in district:
            return v
    return None


def land_type(value: str | None) -> str | None:
    """
    :param dict:
    :return:
    """
    if value is None:
        return None

    property_type_land = {
        "сільгосппризначення": "1",
        "під забудову": "2",
        "промпризначення": "7",
        "комерційного призначення": "7",
    }
    return property_type_land.get(f'{value}')


PROPERTY_TYPE_HOUSES_MAP = {
    'Будинок': 'house',
    'Клубний будинок': 'club_house',
    'Котедж': 'cottage',
    'Частина будинку': 'house_part',
    'Таунхаус': 'townhouse',
    'Кантрі хаус': 'country_house',
    'Дуплекс': 'duplex',
    'Модульні будинки': 'modular_homes',

}


class ProxyManager:
    def __init__(self, api_key: str):
        self.api = Api({"key": api_key})
        self.proxies = []
        self.index = 0

    def load(self):
        result = self.api.proxyList({"type": "ipv4"})

        self.proxies = []

        for proxy in result.get("ipv4", []):
            if proxy.get("status") not in ["Active", 'Ends']:
                continue

            self.proxies.append({
                "ip": proxy["ip"],
                "proxy": (
                    f"http://{proxy['login']}:{proxy['password']}"
                    f"@{proxy['ip']}:{proxy['port_http']}"
                ),
            })

        logger_parser.info("Loaded %s active proxies", len(self.proxies))

    def next(self):
        if not self.proxies:
            raise RuntimeError("No active proxies loaded (proxy list is empty)")

        proxy = self.proxies[self.index]

        self.index += 1

        if self.index >= len(self.proxies):
            self.index = 0

        return proxy

    def log_403(self, proxy, url):
        logger_parser.warning(
            "403 via proxy=%s url=%s",
            proxy["ip"],
            url,
        )


async def extract_full_info(*, session, obj_url):
    latitude = None
    longitude = None
    property_type_houses = None
    year_construction = None
    try:
            status, text = await fetch_full_page(
                session=session,
                url=obj_url,
            )

            if status != 200 or not text:
                return None

            soup = BeautifulSoup(text, 'lxml')
            full_text = None
            descriptions = soup.find_all('div', class_='offer-view-section-text')
            for t in descriptions:
                if full_text is None:
                    full_text = ''

                full_text += f'{t.text.strip()}\n'


            location_block = soup.find('div', class_='offer-view-map')
            if hasattr(location_block, 'script'):
                try:
                    pattern = r"offerMapCoordinates:\s*\[\s*([0-9\.\-]+)\s*,\s*([0-9\.\-]+)\s*\]"
                    match = re.search(pattern, location_block.script.text)

                    if match:
                        lng = float(match.group(1))
                        lat = float(match.group(2))
                        latitude = lat
                        longitude = lng
                except Exception as ex:
                    logger_parser.warning(f'error location - {ex}. Ads url - {obj_url}')

            details = soup.find('div', class_='offer-view-details')
            if details:
                rows = details.find_all('div', class_='offer-view-details-row')
                for r in rows:
                    if not r:
                        continue
                    value = r.text.strip()
                    if value in PROPERTY_TYPE_HOUSES_MAP:
                        property_type_houses = PROPERTY_TYPE_HOUSES_MAP[value]

                    if 'рік побудови' in value:
                        try:
                            year_construction = int(value.replace('рік побудови', '').strip())
                        except Exception as ex:
                            logger_parser.warning(f'Error pars year - {ex}. data: {value}')

            return {
                'description': full_text,
                'latitude': latitude,
                'longitude': longitude,
                'year_construction': year_construction,
                'property_type_houses': property_type_houses,
            }
    except Exception as ex:
        logger_parser.warning(f'error during full_page_info - {ex}- {obj_url}')
    return {'latitude': latitude, 'longitude': longitude}

# new
async def fetch_full_page(
    *,
    session: aiohttp.ClientSession,
    url: str,
):
    for attempt in range(2):

        proxy = proxy_manager.next()

        try:
            async with session.get(
                url=url,
                proxy=proxy["proxy"],
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:

                if response.status == 403:
                    proxy_manager.log_403(proxy, url)

                    if attempt == 0:
                        continue

                if response.status != 200:
                    logger_parser.warning(
                        "Unexpected status %s via proxy %s. url=%s",
                        response.status,
                        proxy["ip"],
                        url,
                    )

                    if attempt == 0:
                        continue

                    return response.status, None

                return response.status, await response.text()

        except Exception as ex:

            logger_parser.warning(
                "Proxy %s failed: %s",
                proxy["ip"],
                ex,
            )

    return None, None

def parse_address(address: str):
    # Знаходимо номер будинку (наприклад: 3, 17-К, 4/1, 12А)
    match = re.search(r'(\d+[\/\-]?\d*[А-Яа-яA-Za-z\-]*)$', address.strip())

    if match:
        house = match.group(1)
        # Все, що перед номером — це адресна частина
        street = address[:match.start()].strip().rstrip(', ')
    else:
        street = address.strip()
        house = None

    return street, house


def exist_contact(db, author_id, platform='RIELTORUA'):
    if not author_id:
        return None

    # Шукаємо існуючий контакт
    existing_contact = db.query(models.ContactPlatform).filter(
        models.ContactPlatform.user_id == author_id,
        models.ContactPlatform.platform == platform
    ).first()

    if existing_contact:
        return existing_contact.contact_id
    return False


def create_contact(db, author_id, author_link, is_realtor, author_name, phone, platform='RIELTORUA'):
    # Шукаємо існуючий контакт
    existing_contact = db.query(models.ContactNew).filter(
        models.ContactNew.phone == phone
    ).first()

    if existing_contact:
        platform_contact = models.ContactPlatform(
            contact_id=existing_contact.id,
            platform=platform,
            user_id=author_id,
            name=author_name,
            phone=phone,
            link=author_link
        )
        db.add(platform_contact)
        db.commit()
        return existing_contact.id
    else:

        # Створюємо новий контакт
        new_contact = models.ContactNew(
            phone=phone,
            name=author_name,

            is_realtor=is_realtor
        )

        db.add(new_contact)
        db.flush()

        platform_contact = models.ContactPlatform(
            contact_id=new_contact.id,
            platform=platform,
            user_id=author_id,
            name=author_name,
            phone=phone,
            link=author_link
        )
        db.add(platform_contact)
        db.commit()

        return new_contact.id


async def get_new_data(*, session, obj_data, rc_lookup):
    """

    :param session:
    :param obj_data:   {

                            "url": url,
                            "cities": cities,
                            "region": region_slug,
                            "type": obj_type,
                            "action": action,
                        }
    :param rc_lookup:
    :return:
    """
    try:
        proxy = proxy_manager.next()

        async with session.get(url=obj_data.get("url"), headers=headers, proxy=proxy['proxy']) as response:  #
            text = await response.text()
            if response.status == 403:
                proxy_manager.log_403(proxy, obj_data.get("url"))
                return

            soup = BeautifulSoup(text, 'lxml')
            exist_objs = soup.find('div', class_='catalog-sort-wrap')
            if exist_objs:
                if 'вашим запитом пропозицій не знайдено' in exist_objs.text.strip():
                    return False

            cards = soup.find_all('div', class_='catalog-card')
            current_ids = []
            for c in cards:
                try:
                    current_ids.append(c.find('div', class_='catalog-card-favorites').get('data-fav-card'))
                except:
                    pass
            exists_db_ids = models.Offer.get_offers_created_at(ad_ids=current_ids, source='RIELTORUA')
            succes_added = []

            for card in cards:
                try:
                    action = obj_data.get("action")
                    type_obj = obj_data.get("type")
                    url = obj_data.get("url")

                    location_slug = card.find('div', class_='catalog-card-region').find('a').get('href').replace("https://rieltor.ua", "") #
                    parts = location_slug.strip('/').split('/')
                    city_slug = f'/{parts[-2]}/' if len(parts) > 1 else '/'

                    city_obj = obj_data['cities'].get(city_slug)
                    if city_obj is None:
                        # logger_parser.info(f'City not found -  slug: {city_slug}. Location - {location_slug}')
                        continue

                    city_id = city_obj.get('id')

                    ads_id = card.find('div', class_='catalog-card-favorites').get('data-fav-card')
                    link = card.find('a', class_='catalog-card-media').get('href')

                    house_number = None
                    address = None
                    property_type_land = None

                    if int(ads_id) not in exists_db_ids:
                        area = None
                        rooms_count = None
                        autor = card.find('button', class_='button-link catalog-card-author-title')

                        if autor is None:
                            author_name = card.find('span', class_='catalog-card-author-title').text
                            author_link = None
                        else:
                            author_name = autor.text
                            link_pars = autor.get('onclick').replace("location.href = 'https://", "").replace(
                                ".rieltor.ua/'", "")
                            author_link = f'https://{link_pars}.rieltor.ua/'

                        phone_block = card.find('div', class_='hide catalog-card-author-phones')

                        if phone_block:
                            phone_pars = phone_block.a.get('href').split('+')[-1]
                            phone_id = f'+{phone_pars.replace("-", "").replace("(", "").replace(")", "").replace(" ", "").strip()}'.replace(
                                "+38", "")

                        floor = None
                        floors = None

                        full_obj = await extract_full_info(session=session, obj_url=link)
                        if full_obj is None:
                            logger_parser.warning(
                                "Skip ad %s: failed to fetch full page",
                                ads_id,
                            )
                            continue

                        description = full_obj.get('description')
                        latitude = full_obj.get('latitude')
                        longitude = full_obj.get('longitude')
                        year_construction = full_obj.get('year_construction')

                        if full_obj.get('description') is None:
                            description = card.find('div', class_='catalog-card-description').text.strip() if card.find(
                                'div', class_='catalog-card-description') else 'немає опису'

                        details = card.find_all('div', class_='catalog-card-details-row')
                        residential_complex = card.find('div', class_='ldb-mini').text.strip() if card.find('div',
                                                                                                            class_='ldb-mini') else None
                        property_type_houses = full_obj.get('property_type_houses')
                        for detail in details:
                            data = detail.text.strip()

                            for l_type in ['під забудову', 'сільгосппризначення', 'промпризначення',
                                           'комерційного призначення']:
                                if l_type in data:
                                    property_type_land = land_type(l_type)
                                    break

                            if ' сот' in data:
                                area_land = data.replace('сот', '').strip()
                                logger_parser.warning(f'LAND: {data.strip().replace("сот", "")}')
                                try:
                                    area = float(area_land)
                                except Exception as ex_area:
                                    logger_parser.warning(f'Error area - {ex_area}. data - {data}')
                            if 'м²' in data:
                                try:
                                    area = float(f'{data.split("/")[0].replace("м²", "").strip()}')
                                except Exception as ex_area:
                                    logger_parser.warning(f'Error area - {ex_area}. data - {data}')
                            if 'кім' in data:
                                rooms_count = data.split(' ')[0].strip()
                            if 'поверх' in data:
                                floor = data.replace('поверх', '').split(' з ')[0].strip()
                                floors = data.replace('поверх', '').split(' з ')[-1].strip()

                        subway_id = None
                        subway_block = c.find('a', class_='catalog-card-chip -subway')

                        if subway_block and int(city_id) == 10:  # Kiev
                            subway_id = kiev_metro_by_name.get(subway_block.text.strip(), None)

                        price_full = card.find('strong', class_='catalog-card-price-title').text.strip()
                        if '€' in price_full:
                            currency = 'EUR'
                        elif '$' in price_full:
                            currency = 'USD'
                        else:
                            currency = 'UAH'

                        cut_price = price_full.replace('$/міс', '').replace('/міс', '').replace('грн/міс', '').replace(
                            '$', '').replace('грн', '').replace(' ', '').replace("€", '').strip()
                        price = int(cut_price)
                        labels = card.find('div', class_='catalog-card-chips')
                        no_commission = None
                        is_e_vidnovlennia = False
                        e_oselya = False
                        if labels:
                            labels_text = labels.text
                            if 'БЕЗ КОМІСІЇ' in labels_text:
                                no_commission = True
                            if 'єОселя' in labels_text:
                                is_e_vidnovlennia = True
                            if 'єВідновлення' in labels_text:
                                e_oselya = True

                        if no_commission is None:
                            no_commission = validate_addition_params.detect_no_commission(text=description)

                        base_price = 0  # Add base_price in UAH
                        if price is not None:
                            base_price = await currency_converter.convert_to_uah(price, currency or 'UAH')

                        address_block = card.find('div', class_='catalog-card-address').text.strip()
                        district_id = None
                        district = card.find('div', class_='catalog-card-region')
                        if str(city_id) == str(10) and district:
                            district_id = district_pars(district.text.strip())

                        address = None if 'район' in address_block else address_block
                        if address:
                            try:
                                address, house_number = parse_address(address=address)
                                if address:
                                    address = address.replace('C.', '').replace('с.', '').replace('м.', '').replace(
                                        'смт.', '').replace('Смт.', '').replace(f'{city_obj.get("name")},', '').strip()
                            except:
                                pass

                        imgs = card.find_all('img', class_='offer-photo-slider-slide-image')

                        pictures = [
                            'https:/' + x.get('src').split('crop/')[-1][7:].replace("480/360", "960/720")
                            for x in imgs]

                        if 'flats' in url:
                            head = f"Квартира"
                        elif 'rooms' in url:
                            head = f"Комната"
                        elif 'areas' in url:
                            head = f"Ділянка"

                        elif 'commercial' in url:
                            head = f"Комерційне приміщення"
                        else:
                            head = f"Будинок"
                            floor = None
                            floors = None

                        if type_obj == 'house' and property_type_houses is None:
                            property_type_houses = validate_addition_params.detect_property_type_houses(
                                text=description)

                        if address is None:
                            address = ''

                        repair = None
                        if action == 'sale':
                            repair = '1' if await ai_repair.has_repair(text=description) else None

                        offer_data = {
                            'ad_id': ads_id,
                            'title': f'{head}. {city_obj.get("name")}, {address}',
                            'repair': repair,
                            'owner_type': "business",
                            'source': 'RIELTORUA',
                            'year_construction': year_construction,
                            'property_type_houses': property_type_houses,
                            'price': price,
                            'currency': currency.lower() or 'uah',
                            'type': type_obj,
                            'action': action,
                            'no_commission': no_commission,
                            'is_e_vidnovlennia': is_e_vidnovlennia,
                            'city_id': city_id,
                            'district_id': district_id,
                            'region_id': city_obj.get('region_id'),
                            'street': None if len(address) < 4 else address,
                            'house_number': None if address is None else house_number,
                            'residential_complex': residential_complex,
                            'floors': floors,
                            'floor': floor,
                            'property_type_land': property_type_land,
                            'total_area': area,
                            'longitude': longitude,
                            'latitude': latitude,
                            'rooms': rooms_count,
                            'updated_at': datetime.now(),
                            'ad_link': link,
                            'subway_id': subway_id,
                            'description': description,
                            'main_photo': pictures[0],
                            'photos': pictures,
                            'e_oselya': e_oselya,
                            'refresh_time': datetime.now(),
                            'created_at': datetime.now(),

                        }

                        if offer_data.get('street'):
                            street = offer_data.get('street')
                            house_number = offer_data.get('house_number')

                            # якщо є номер будинку — додаємо
                            if house_number:
                                street = f"{street} {house_number}"

                            map_position = location_api.get_location(
                                city_id=offer_data.get('city_id'),
                                street=street
                            )
                            offer_data['microdistrict_id'] = map_position.get('microdistrict_id')
                            if map_position.get('street'):
                                offer_data['street'] = map_position.get('street')

                            if map_position.get('lat') and map_position.get('lon'):
                                offer_data['latitude'] = map_position.get('lat')
                                offer_data['longitude'] = map_position.get('lon')

                        if (
                                (
                                        action == 'sale'
                                        and
                                        city_obj.get(
                                            'ai_processed')
                                        and type_obj in SALE_AI_PROPERTIES_TYPE
                                )
                                or (

                                offer_data.get('city_id') == 10  # тільки Київ
                                and action == 'rent'  # Оренда
                                and type_obj in RENT_AI_PROPERTIES_TYPE
                        )
                        ):

                            # ai reach offer params
                            if str(offer_data.get('city_id')) == str(10):  # Київ
                                missing_fields = [f for f in ai_agent.AI_EXTRACTABLE_FIELDS_KYIV if
                                                  not offer_data.get(f)]
                            else:
                                missing_fields = [f for f in ai_agent.AI_EXTRACTABLE_FIELDS_REGION if
                                                  not offer_data.get(f)]

                            if missing_fields:
                                ai_result = await ai_agent.addition_params(
                                    version=settings.PROMPT_VERSION,
                                    prompt_id=settings.PROMPT_ID,
                                    input_msg=f'Знайди цей перелік полів:{missing_fields}\n\n{offer_data.get("title")}\n'
                                              f'Опис: {offer_data.get("description")}\n'
                                )

                                if ai_result:
                                    for field in missing_fields:
                                        ai_value = ai_result.get(field)
                                        if ai_value is not None:
                                            offer_data[field] = ai_value
                                            logger_parser.warning(
                                                f'🟩️️️️️️AI recognize ad_id: {ads_id}. Set extra params field {field}: {ai_value}')

                                    if offer_data.get('residential_complex'):

                                        residential_complex_db = rc_lookup.get(int(offer_data.get('city_id')))
                                        if residential_complex_db:
                                            residential_complex_data = residential_complex_db.get(
                                                normalize(offer_data.get('residential_complex')))
                                            if residential_complex_data:
                                                offer_data['residential_complex'] = residential_complex_data.get(
                                                    "origin")
                                                offer_data['housing_complex_id'] = residential_complex_data.get("id")
                                                logger_parser.info(
                                                    f'🏘Set residential_complex - {residential_complex_data.get("origin")} with id {residential_complex_data.get("id")}')


                        with db_session() as db:
                            existing = db.query(models.Offer).filter(
                                models.Offer.ad_id == ads_id,
                                models.Offer.source == 'RIELTORUA'
                            ).first()

                            if existing and ads_id not in succes_added:
                                continue

                            # Отримуємо або створюємо контакт
                            contact_id = exist_contact(
                                db=db,
                                author_id=phone_id
                            )

                            if contact_id is False:
                                contact_id = create_contact(db=db,
                                                            author_id=phone_id,
                                                            author_link=author_link,
                                                            is_realtor=1 if author_link else 0,
                                                            phone=f'+38{phone_id}',
                                                            author_name=author_name)
                                offer_data['contact_id'] = contact_id
                            else:
                                offer_data['contact_id'] = contact_id

                            offer_data['is_realtor'] = 1 if author_link else 0

                            raw_offer = models.Offer(**offer_data)
                            db.add(raw_offer)
                            db.commit()
                            db.refresh(raw_offer)
                            logger_parser.warning(f'Create new ads - {link}')
                            succes_added.append(ads_id)
                            if offer_data.get('action') == 'sale' and offer_data.get(
                                    'type') in ['apartment', 'house']:
                                if city_obj.get(
                                            'detect_photo_duplicates'):
                                    await api_send_task({
                                        "ad_id": offer_data.get('ad_id'),
                                        "db_id": raw_offer.id,  # pk
                                        "action": offer_data.get('action'),
                                        "source": "RIELTORUA",
                                        "type_obj": offer_data.get('type'),
                                        "city_id": offer_data.get('city_id'),
                                        "base_price": base_price,
                                        "created_at": int(datetime.now().timestamp())
                                    })
                                    logger_parser.info(
                                        f'Send obj to vector service api - {offer_data.get("ad_id")}. db_id = {raw_offer.id}')

                except Exception as er:
                    logger_parser.warning(f'during parser ex {er} - ads id: {ads_id}. {url}')
    except Exception as ex:
        logger_parser.warning(f'ПОМИЛКА ПАРСИНГУ RIELTOR UA {ex}')

    return True


def normalize(text: str) -> str:
    """Нижній регістр + trim + видаляємо префікс ЖК/жк."""
    if not text:
        return ''
    t = text.strip().lower()
    # Видаляємо "жк " або "жк." на початку
    for prefix in ('жк ', 'жк.'):
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
            break
    return t


def build_rc_lookup():
    """
    city_id → {
        normalize(назва) → {
            "origin": original_text,
            "id": rc_id
        }
    }
    """
    with db_session() as session:
        rc_rows = session.query(
            models.ResidentialComplex.id,
            models.ResidentialComplex.title,
            models.ResidentialComplex.keywords,
            models.ResidentialComplex.city_id,
        ).all()

    lookup: dict[int, dict[str, dict]] = defaultdict(dict)

    for r in rc_rows:
        if not r.title or not r.city_id:
            continue

        canonical = r.title.strip()
        norm_title = normalize(canonical)

        city_lookup = lookup[r.city_id]

        # Основна назва
        city_lookup[norm_title] = {
            "origin": canonical,
            "id": r.id
        }

        # Keywords
        if r.keywords:
            kw_list = (
                r.keywords if isinstance(r.keywords, list)
                else r.keywords.values() if isinstance(r.keywords, dict)
                else []
            )

            for kw in kw_list:
                if isinstance(kw, str) and kw.strip():
                    city_lookup[normalize(kw)] = {
                        "origin": kw.strip(),
                        "id": r.id
                    }

    return dict(lookup)


async def task_watch():

    logger_parser.info(f"start task +")
    rc_lookup = build_rc_lookup()

    await currency_converter.update_exchange_rates()

    try:

        async with aiohttp.ClientSession() as session:

            urls = []

            for region_obj in REGIONS:
                cities = models.City.get_active_rieltorua_cities(regiod_id=region_obj.get('id'))

                if not cities:
                    continue

                region_slug = quote(region_obj.get('slug'))
                logger_parser.info(f'Start region - {region_obj.get("slug")}')

                for action, obj_type in URLS:

                    url = (
                        f"https://rieltor.ua/"
                        f"{TYPE_MAP[obj_type]}-{ACTION_MAP[action]}/"
                        f"{region_slug}/"
                        f"?sort=bycreated"

                    )

                    urls.append(
                        {

                            "url": url,
                            "cities": cities,
                            "region": region_slug,
                            "type": obj_type,
                            "action": action,
                        }

                    )

            for page in range(1, 3 if region_obj.get('id') == 10 else 2):

                for obj_data in urls:
                    obj = obj_data.copy()

                    if page > 1:
                        obj["url"] = f"{obj['url']}&page={page}"

                    await get_new_data(
                        session=session,
                        obj_data=obj,
                        rc_lookup=rc_lookup
                    )

    except Exception as ex:
        logger_parser.warning(f"task_watch - {ex}")

    logger_parser.info(f"+ end task +")


if __name__ == '__main__':
    proxy_manager = ProxyManager(settings.PROXY_SELLER_KEY)
    proxy_manager.load()

    if not proxy_manager.proxies:
        logger_parser.warning("No active proxies loaded, aborting run")
    else:
        asyncio.run(task_watch())
