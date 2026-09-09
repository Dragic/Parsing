import logging
import random
import asyncio
from collections import defaultdict

from curl_cffi import requests
import models
import time
import ai_repair
import location_api
import validate_addition_params
from settings import settings
import utils
from datetime import datetime, timedelta
from database import db_session
from log import logger
from send_message import telegram_message
from api_phone_service import add_task_to_phone
from vector_service import api_send_task
import ai_agent

# Import the currency converter
from currency_api import currency_converter

logger_main = logging.getLogger('log.main_monitoring.py')

UPDATE_UNIQUE = settings.UPDATE_ADS

IMPERSONATE = 'chrome'
EXTRA_HEADERS = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'accept-language': 'uk-UA,uk;q=0.9,ru;q=0.8,en-US;q=0.7,en;q=0.6',
}

# Семафор для обмеження кількості одночасних запитів
SEMAPHORE = asyncio.Semaphore(1)


# AI additions params recognize
SALE_AI_PROPERTIES_TYPE = ['apartment', 'house', 'commercial']
RENT_AI_PROPERTIES_TYPE = ['apartment', 'house', 'commercial']


class Stats:
    total_new = 0


stats = Stats()

OLX_TO_DATABASE_MAPPING = {
    'property_type_houses': {
        'Будинок': 'house',
        'Клубний будинок': 'club_house',
        'Котедж': 'cottage',
        'Частина будинку': 'house_part',
        'Таунхаус': 'townhouse',
        'Дача': 'country_house',
        'Дуплекс': 'duplex',
        'Модульні будинки': 'modular_homes'
    },
    'property_type_land': {
        'Земля сільськогосподарського призначення': 1,
        'Земля житлової й суспільної забудови': 2,
        'Земля оздоровчого призначення': 3,
        'Земля рекреаційного призначення': 4,
        'Земля лісового фонду': 5,
        'Земля водного фонду': 6,
        'Земля промисловості, транспорту та іншого призначення': 7,
        'Земля запасу, резервного фонду та загального користування': 8
    },
    'communications': {
        'Газ': 'gas',
        'Центральний водопровід': 'water_central',
        'Свердловина': 'well',
        'Електрика': 'electricity',
        'Центральна каналізація': 'central_sewerage_system',
        'Каналізація септик': 'sewerage_septic_tank',
        'Вивіз відходів': 'garbage_removal',
        'Асфальтована дорога': 'asphalt_road',
        'Без комунікацій': 'no_comm'
    },
    'repair': {
        'Авторський проект': "1",
        'Євроремонт': "2",
        'Косметичний ремонт': "3",
        'Житловий стан': "4",
        'Після будівельників': "5",
        'Під чистову обробку': "6",
        'Аварійний стан': "7"
    },
    'comm_re_type': {
        'Бізнес центр': 'business_center',
        'Торгово-офісний центр': 'trade_and_office_building',
        'Адміністративна будівля': 'administrative_building',
        'Нежитлове приміщення у житловому фонді': 'non_residential_item_in_residential_building',
        'Житловий фонд': 'residential_building',
        'Інше': 'other'
    },
    'apartment_type': {
        'Будинок до 1917 року': "1",
        'Сталінка': "2",
        'Хрущовка': "3",
        'Чешка': "4",
        'Гостинка': "5",
        'Совмін': "6",
        'Гуртожиток': "7",
        'Житловий фонд 80-90-і': "8",
        'Житловий фонд 91-2000-і': "9",
        'Житловий фонд 2001-2010-і': "10",
        'Житловий фонд 2011-2020-і': "11",
        'Житловий фонд від 2021 р.': "12"
    },
    'layout': {
        "Окремі кімнати": "separate",
        "Суміжні кімнати": "adjacent_through",
        "Студія": "studio",
        "Вільне планування": "free_layout",
    },
    'bathroom': {
        "Роздільний": "1",
        "Суміжний": "2",
        "2 і більше": "3",
        "Санвузол відсутній, У дворі": "4"
    },
    'heating': {
        "Централізоване": "centralized",
        "Власна котельня": "own_boiler-house",
        "Індивідуальне газове": "individual_gas",
        "Індивідуальне електро": "individual_electro",
        "Твердопаливне": "solid_fuel",
        "Тепловий насос": "heat_pump",
        "Комбіноване": "combined",
        "Інше": "other"
    },
    'appliances': {
        'Плита': 'stove',
        'Варильна панель': 'hob',
        'Духова шафа': 'oven',
        'Мікрохвильова піч': 'microwave',
        'Холодильник': 'fridge',
        'Посудомийна машина': 'dishwasher',
        'Пральна машина': 'washer',
        'Сушильна машина': 'drying_machine',
        'Електрочайник': 'electric_kettle',
        'Кавомашина': 'coffeemachine',
        'Фен': 'hair_dryer',
        'Мультиварка': 'multi-cooking',
        'Праска': 'iron',
        'Вентилятор, обігрівач': 'fan_heater',
        'Кулер': 'cooler',
        'Пилосос': 'vacuum_cleaner',
        'Без побутової техніки': 'no_appliances'
    },
    'multimedia': {
        'Wi-Fi': 'wifi',
        'Швидкісний інтернет': 'speed_internet',
        'Телевізор': 'tv',
        'Кабельне, цифрове ТБ': 'cable_digital',
        'Супутникове ТБ': 'satellite',
        'Без мультимедіа': 'no_multimedia'
    },
    'comfort': {
        'Кондиціонер': 'air_conditioning',
        'Підігрів підлоги': 'heated_floors',
        'Ванна': 'bath',
        'Меблі на кухні': 'kitchen_furniture',
        'Гардероб': 'wardrobe',
        'Балкон, лоджія': 'balcony_loggia',
        'Тераса': 'terrace',
        'Панорамні вікна': 'panoramic_windows',
        'Грати на вікнах': 'windows_lattices',
        'Сигналізація': 'signaling',
        'Пожежна сигналізація': 'fire_alarm',
        'Відеоспостереження': 'CCTV',
        "Конс'ерж": 'concierge',
        'Охорона території': 'protected_area',
        'Паркувальне місце': 'parking_place',
        'Гостьовий паркінг': 'guest_parking',
        'Підземний паркінг': 'ground_parking',
        'Гараж': 'garage',
        'Ліфт': 'elevator',
        'Грузовий ліфт': 'service_lift',
        'Госп. приміщення, комора': 'storage',
        'Технологія "розумний будинок"': 'tech_smart_house',
        'Автономний електрогенератор': 'stand-alone_power',
        'Душова кабіна': 'shower_cabin',
        'Балкон': 'balcony',
        'Камін': 'fireplace',
        'Огорожа': 'fence',
        'Автонавіс': 'auto-weight',
        'Автоматичні ворота': 'automatic_gates',
        'Гостьовий, літній будинок': 'huest_house',
        'Альтанка, мангал': 'BBQ',
        'Підсобні приміщення': 'a_room',
        'Спортзал': 'gym',
        'Сауна, баня': 'sauna',
        'Басейн': 'swimming_pool',
        'Сад, город': 'garden',
        'Цоколь, підвал': 'basement',
        'Сонячні електропанелі': 'solar_panels',
        'Вітрова електростанція': 'wind_power_plant'
    },
    'infrastructure_500_m': {
        'Дитячий садок': 'kindergarten',
        'Школа': 'school',
        'Бювет': 'pump',
        'Зупинка транспорту': 'transport_stop',
        'Метро': 'metro',
        'Ринок': 'market',
        'Магазин, кіоск': 'shop_kiosk',
        'Супермаркет, ТРЦ': 'supermarket_mall',
        'Парк, зелена зона': 'park',
        'Дитячий майданчик': 'playground',
        'Аптека': 'farmacy',
        'Лікарня, поліклініка': 'hospital',
        'Центр міста': 'city_center',
        'Ресторан, кафе': 'restaurant_cafe',
        'Кінотеатр, театр': 'cinema_theater',
        'Відділення пошти': 'post_office',
        'Відділення банку, банкомат': 'bank_ATM',
        'Автовокзал': 'bus_station',
        'Залізнична станція': 'railway_station'
    },
    'ecosystem_1_km': {
        'Річка': 'river',
        'Водосховище': 'reservoir',
        'Озеро': 'lake',
        'Море': 'sea',
        'Острови': 'islands',
        'Пагорби': 'hills',
        'Гори': 'mountains',
        'Парк': 'park',
        'Ліс': 'forest'
    },
    'blackout_autonomy': {
        'Працює інтернет': 'internet',
        'Працює ліфт': 'elevator',
        'Працює водопопостачання': 'water_supply',
        'Працює опалення': 'heating',
        'Підключене резервне живлення': 'backup_power_supply'
    }
}


def filter_msg_to_telegram(*, ad, property_type, action, main_photo, rooms, floor, floors):
    # Чат_3
    # "olx_id":"295","name":"Ірпінь"
    # "olx_id":"30599","name":"Ворзель"
    # "olx_id":"28","name":"Буча"
    # "olx_id":"435","name":"Гостомель"
    # # Дмитрівка (Буча)
    # "olx_id":"31905","name":"Гореничі"
    # "olx_id":"31965","name":"Стоянка"
    # "olx_id":"31077","name":"Блиставиця"
    # "name":"Михайлівка-Рубежівка (Бучанський)
    # "name":"Михайлівка-Рубежівка (Ірпінь)"
    # "olx_id":"32053","name":"Макарів"
    # "olx_id":"31917","name":"Забуччя"
    # "olx_id":"31111","name":"Загальці"
    # "olx_id":"31113","name":"Здвижівка"
    # "olx_id":"31919","name":"Капітанівка"
    # Лісне (Бучанський)
    # "olx_id":"31941","name":"Мила"
    # "olx_id":"32491","name":"Романівка"
    # "olx_id":"31117","name":"Клавдієво-Тарасове"
    #
    # Чат_2
    # "olx_id":"268","name":"Київ"

    #
    # Чат_1
    # "olx_id":"295","name":"Ірпінь"
    # "olx_id":"30599","name":"Ворзель"
    # "olx_id":"28","name":"Буча"
    # "olx_id":"435","name":"Гостомель"
    chat_1 = '-1002502617950'
    chat_2 = '-1002621565826'
    chat_3 = '-1002603232813'

    price = 0
    currency = 0
    exclude_property_type_houses = ['Модульні будинки', 'Дача']
    property_type_houses = None
    try:
        for param in ad['params']:
            if param['key'] == 'price' and param['value']:
                price = param['value'].get('value')
                currency = param['value'].get('currency')

            if param['key'] == 'property_type_houses' and param['value']:
                property_type_houses = param['value'].get('label', '-')

        city_name = ad.get('location', {}).get('city', {}).get('name')

        city_id = ad.get('location', {}).get('city', {}).get('id')
        action_name = 'Продаж' if action == 'sale' else 'Оренда'
        rooms_name = 'Другое' if rooms is None else f'{rooms}к'

        msg = f'<a href="{main_photo};s=600x600">🏢</a>- {city_name}\n' \
              f'- {action_name}\n' \
              f'- {price} {currency}\n' \
              f'- {rooms_name}\n' \
              f'{floor}|{floors}\n' \
              f"{ad.get('url')}"

        # 🔹 Чат 1: Квартиры, Продажа, Ірпінь, Ворзель, Буча, Гостомель
        CHAT_1_CITIES = {"295", "30599", "28", "435"}
        if (
                property_type == "apartment"
                and action == "sale"
                and str(city_id) in CHAT_1_CITIES
        ):
            telegram_message(chat_id=chat_1, text=msg, ads_url=ad.get("url"))
            return

        # 🔹 Чат 2: Квартиры, Продажа, Київ
        if property_type == "apartment" and action == "sale" and city_id == 268:
            telegram_message(chat_id=chat_2, text=msg, ads_url=ad.get("url"))
            return

        # 🔹 Чат 3: Дома, Продажа, зони Бучанського району
        CHAT_3_CITIES = {
            "295", "30599", "28", "435", "31905", "31965", "31077", "32053", "31917",
            "31111", "31113", "31919", "31941", "32491", "31117"
        }
        # Також додаткові назви по назві міста
        CHAT_3_CITY_NAMES = {
            "дмитрівка", "гореничі", "стоянка", "блиставиця", "михайлівка", "макарів",
            "забуччя", "загальці", "здвижівка", "капітанівка", "лісне", "мила", "романівка", "клавдієво"
        }

        city_name_lower = city_name.lower()

        if (
                property_type == "house"
                and property_type_houses not in exclude_property_type_houses
                and action == "sale"
                and (str(city_id) in CHAT_3_CITIES or any(name in city_name_lower for name in CHAT_3_CITY_NAMES))
        ):
            telegram_message(chat_id=chat_3, text=msg, ads_url=ad.get("url"))
            return
    except Exception as ex:
        logger_main.warning(f'During filter msg - {ex} - {ad.get("url")}')


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

    total_keys = sum(len(v) for v in lookup.values())

    return dict(lookup)


def apply_location(offer_data: dict) -> dict:
    """Resolve street/house into microdistrict + coordinates via the geocoder API.

    Kept separate from add_extra_params: geocoding must not depend on whether the
    AI enrichment step ran for this city/action, otherwise most listings are
    stored without coordinates at all.
    """
    if not offer_data.get('street'):
        return offer_data

    try:
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
        # The source string is deliberately kept: it is the raw material the street
        # alias dictionary is built from, and OLX has no reliable house number to
        # fall back on. Only the derived fields below are taken from the geocoder.
        if map_position.get('lat') and map_position.get('lon'):
            offer_data['latitude'] = map_position.get('lat')
            offer_data['longitude'] = map_position.get('lon')

    except Exception as ex:
        logger_main.warning(f'Error during geocoding - {ex}. ad:{offer_data.get("ad_id")}')

    return offer_data


async def add_extra_params(ad, offer_data) -> dict:
    try:
        location_city = ad.get('location', {}).get('city', '')
        if location_city == 'Київ':  # metro station
            missing_fields = [f for f in ai_agent.AI_EXTRACTABLE_FIELDS_KYIV if not offer_data.get(f)]
        else:
            missing_fields = [f for f in ai_agent.AI_EXTRACTABLE_FIELDS_REGION if not offer_data.get(f)]

        if missing_fields:
            ai_result = await ai_agent.addition_params(
                version=settings.PROMPT_VERSION,
                prompt_id=settings.PROMPT_ID,
                input_msg=f'Знайди цей перелік полів:{missing_fields}\n\n {ad.get("title")}\n'
                          f'Опис: {ad.get("description")} {offer_data.get("residential_complex", "")}\n'
                          f'Місто: {location_city}'
            )

            if ai_result:
                for field in missing_fields:
                    ai_value = ai_result.get(field)
                    if ai_value is not None:
                        offer_data[field] = ai_value
                        logger_main.warning(
                            f'🟩️️️️️️AI recognize ad_id: {offer_data.get("ad_id")}. Set extra params field {field}: {ai_value}')

    except Exception as ex:
        logger_main.warning(f'Error during recognize extra params - {ex}. ad:{offer_data.get("ad_id")}')

    finally:
        return offer_data


def get_or_create_contact(db, author_id, is_realtor, platform='OLX', author_name=None, ads_id=None):
    if not author_id:
        return None

    # Шукаємо існуючий контакт
    existing_contact = db.query(models.ContactPlatform).filter(
        models.ContactPlatform.user_id == author_id,
        models.ContactPlatform.platform == platform,
        models.ContactPlatform.name == author_name
    ).first()

    if existing_contact:
        if existing_contact.phone:
            return existing_contact.contact_id
        else:
            # якщо є контакт без телефона, пробуємо повторно дістати телефон
            add_task_to_phone(ad_id=ads_id, user_id=author_id, name=author_name, is_realtor=is_realtor)
            return None

    add_task_to_phone(ad_id=ads_id, user_id=author_id, name=author_name, is_realtor=is_realtor)


    return None


def set_call_status(city_id, property_type, action, is_realtor) -> bool:
    city_list = ['10', '220', '612', '17503', '17504', '214', '31963', '31959']
    property_list = ['apartment', 'house', 'room']
    if property_type in property_list and action == 'sale' and str(city_id) in city_list and is_realtor == 0:
        return True
    return False


async def extract_data(url: str, region_obj: dict, action: str, rc_lookup: dict, name_category: str, region_id: int, session) -> bool:
    offer_to_update = defaultdict(list)
    offer_to_create = []
    try:
        ads_list = None
        city_olx_ids = region_obj.get('city_olx_ids', [])

        async with SEMAPHORE:
            try:
                response = session.get(
                    url,
                    timeout=15,
                    headers={**settings.HEADERS, **EXTRA_HEADERS},
                    proxy=settings.PROXY,
                    impersonate=IMPERSONATE,
                )
                if response.status_code > 201:
                    logger_main.warning(f'Bad response olx. Response: {response.status_code}. Url: {url} ')
                    return True

                response_json = response.json()
                ads_list = response_json['data']

                if len(ads_list) == 0:
                    return False
            except Exception as ex:
                logger_main.warning(f'HTTP request error: {ex}')
                return False

            new_rows = []
            print(f'Pars url - {url}')
            page_ads_ids = [ad.get('id') for ad in ads_list]

            offers_per_page = models.Offer.get_offers_created_at_olx(ad_ids=page_ads_ids, source='OLX')
            # offers_per_page = models.Offer.get_offers_created_at(ad_ids=page_ads_ids, source='OLX')

            for ad in ads_list:
                try:
                    with db_session() as db:
                        print(f'Try {ad.get("id")}')

                        city_olx_id = ad.get('location', {}).get('city', {}).get('id')
                        district = ad.get('location', {}).get('district', {}).get('id')

                        district_id = None
                        if city_olx_id not in city_olx_ids:
                            continue

                        if district:
                            try:
                                districts = region_obj['city'].get(city_olx_id, {}).get('districts', [])
                                for d in districts:
                                    if d.get('olx_id') == district:
                                        district_id = d.get('id')
                            except:
                                pass

                        ads_id = ad.get('id')

                        author_id = ad.get('user', {}).get('id')
                        author_name = ad.get('user', {}).get('name')
                        has_phone = ad.get('contact', {}).get('phone')

                        existing_offer = offers_per_page.get(ads_id)

                        print(f'Pars ads - {ads_id} - {datetime.now()}')

                        # Отримання адреси, якщо є
                        street = None
                        house_number = None
                        market_type = None

                        # Отримання ціни
                        price = None
                        currency = None

                        property_type = settings.SLUG_TYPE_OBJ.get(name_category)

                        property_type_houses = None
                        property_type_land = None
                        comm_re_type = None
                        apartment_type = None
                        property_type_parking = None
                        repair_info = None
                        layout = None
                        bathroom = None
                        heating = None
                        garage_type = None
                        is_furnished = None
                        communications = []
                        appliances = []
                        comfort = []
                        multimedia = []
                        infrastructure_500_m = []
                        ecosystem_1_km = []
                        blackout_autonomy = []

                        kitchen_area = None
                        year_of_commissioning = None

                        if 'params' in ad:
                            for param in ad['params']:
                                if param['key'] == 'kitchen_area' and param['value']:
                                    kitchen_label = param['value'].get('key')
                                    try:
                                        kitchen_area = float(kitchen_label)
                                    except ValueError:
                                        kitchen_area = None
                                    break

                        if 'params' in ad:
                            for param in ad['params']:

                                if param['key'] in ['furnishing', 'furnish']:
                                    is_furnished = False if param['value'].get('key') == 'no' else True

                                if param['key'] == 'price' and param['value']:
                                    price = param['value'].get('value')
                                    currency = param['value'].get('currency')

                                # Тип дома
                                if param['key'] == 'repair' and param['value']:
                                    repair_info = param['value'].get('label')

                                if param['key'] == 'bathroom' and param['value']:
                                    bathroom = param['value'].get('label')

                                if param['key'] == 'layout' and param['value']:
                                    layout = param['value'].get('label')

                                if param['key'] == 'heating' and param['value']:
                                    heating = param['value'].get('label')

                                # Комунікації
                                if param['key'] == 'communications' and param['value']:
                                    try:
                                        # com_label = param['value'].get('label')
                                        communications = param['value'].get('key', [])
                                    except:
                                        pass

                                if param['key'] == 'appliances' and param['value']:
                                    try:
                                        appliances = param['value'].get('key', [])
                                    except:
                                        pass

                                if param['key'] in ['comfort', 'comfort_3'] and param['value']:
                                    try:
                                        comfort = param['value'].get('key', [])
                                    except:
                                        pass
                                if param['key'] == 'garage_type':
                                    garage_type = param['value'].get('key')

                                if param['key'] == 'property_type_parking':
                                    property_type_parking = param['value'].get('key')

                                if param['key'] == 'multimedia_2' and param['value']:
                                    try:
                                        multimedia = param['value'].get('key', [])
                                    except:
                                        pass

                                if param['key'] in ['infrastructure_500_m', 'infrastructure2_500_m'] and param['value']:
                                    try:
                                        infrastructure_500_m = param['value'].get('key', [])
                                    except:
                                        pass

                                if param['key'] == 'ecosystem_1_km' and param['value']:
                                    try:
                                        ecosystem_1_km = param['value'].get('key', [])
                                    except:
                                        pass

                                if param['key'] == 'blackout_autonomy' and param['value']:
                                    try:
                                        blackout_autonomy = param['value'].get('key', [])
                                    except:
                                        pass

                        if action:
                            for param in ad['params']:
                                if param['key'] == 'apartments_object_type':
                                    market_type = 'primary' if param['value'].get('label') == 'Новобудова' \
                                        else 'secondary'
                                # Тип дома
                                if param['key'] == 'property_type_houses' and param['value'] and property_type == 'house':
                                    property_type_houses = param['value'].get('key')

                                # Тип недвижимости земля
                                if param['key'] == 'property_type_land' and param['value'] and property_type == 'land':
                                    property_type_land = param['value'].get('key')

                                # Тип комерції
                                if param['key'] == 'comm_re_type' and param['value'] and property_type == 'commercial':
                                    comm_re_type = param['value'].get('label')

                                # рік введення в експлатацію
                                if param['key'] == 'year_of_commissioning':
                                    try:
                                        year_of_commissioning = int(param['value'].get('key', '').replace(' ', '').strip())
                                    except Exception as e:
                                        logger_main.warning(f'Error params year_of_commissioning - {e}. {ads_id}')

                                # Тип дома для продажі квартир
                                if param['key'] == 'property_type_appartments_sale' and param[
                                    'value'] and property_type == 'apartment':
                                    apartment_type = param['value'].get('label')

                        market_type = market_type if market_type else 'secondary'

                        # Кількість кімнат
                        rooms = None
                        for param in ad['params']:
                            if param['key'] == 'number_of_rooms_string' and param['value']:
                                rooms_label = param['value'].get('label', '')
                                if rooms_label:
                                    # Витягуємо кількість кімнат з тексту (наприклад, "1 комната")
                                    try:
                                        rooms = int(rooms_label.split()[0])
                                    except (ValueError, IndexError):
                                        rooms = None
                                break

                        cadastral_number = None
                        for param in ad['params']:
                            if param['key'] == 'cadastral_number':
                                cadastral_number = param['value'].get('key') if ':' in param['value'].get('key') else None
                                break

                        # Загальна площа
                        total_area = None
                        land_area = None
                        for param in ad['params']:
                            if param['key'] == 'total_area' and param['value']:
                                area_label = param['value'].get('key')
                                if area_label:
                                    try:
                                        total_area = float(area_label)
                                        if total_area > 1000:
                                            total_area = None
                                    except ValueError:
                                        total_area = None

                            if param['key'] == 'land_area' and param['value']:
                                area_label = param['value'].get('key')
                                if area_label:
                                    try:
                                        land_area = float(area_label)
                                    except ValueError:
                                        land_area = None

                        # Поверховість
                        floor = None
                        floors = None
                        for param in ad['params']:
                            if param['key'] == 'floor' and param['value']:
                                try:
                                    floor = int(param['value'].get('key'))
                                except (ValueError, TypeError):
                                    floor = None

                            if param['key'] == 'total_floors' and param['value']:
                                try:
                                    floors = int(param['value'].get('key'))
                                except (ValueError, TypeError):
                                    floors = None

                        # Житловий комплекс
                        residential_complex = None
                        for param in ad['params']:
                            if param['key'] == 'zkh' and param['value']:
                                residential_complex = param['value'].get('key')
                                break

                        # Без комісії
                        no_commission = False
                        is_exchange = None
                        cooperate = None
                        office_type = None
                        office_class = None

                        for param in ad['params']:
                            if param['key'] == 'commission':
                                no_commission = True if param['value'].get('key') == '1' else False
                            if param['key'] == 'is_exchange':
                                is_exchange = True if param['value'].get('key') == '1' else False

                            if param['key'] == 'cooperate':
                                cooperate = True if param['value'].get('key') == '1' else False

                            if param['key'] == 'office_type':
                                office_type = param['value'].get('key')

                            if param['key'] == 'office_class':
                                office_class = param['value'].get('key')

                        # Фото
                        main_photo = None
                        photos = []
                        if 'photos' in ad and ad['photos']:
                            for i, photo in enumerate(ad['photos']):
                                photo_url = photo.get('link').replace(';s={width}x{height}', '')
                                if i == 0:
                                    main_photo = photo_url
                                photos.append(photo_url)

                        # Перевірка на поля e_oselya
                        e_oselya = 0
                        for param in ad['params']:
                            if param['key'] == 'eoselia' and param['value']:
                                e_oselya = 1 if param['value'].get('key') == '1' else 0
                                break

                        from_developer = 0
                        for param in ad['params']:
                            if param['key'] == 'from_developer':
                                from_developer = 1 if param['value'].get('key') == '1' else 0
                                break

                        # Визначення дати оновлення/створення
                        created_at = datetime.now()
                        updated_at = None
                        refresh_time = None

                        if 'last_refresh_time' in ad:
                            try:
                                refresh_time = datetime.fromisoformat(ad['last_refresh_time'])
                                updated_at = refresh_time
                            except (ValueError, TypeError):
                                pass

                        business_private = 'business' if ad.get('business') else 'private'

                        # Calculate base_price in UAH
                        base_price = 0
                        if price is not None:
                            base_price = await currency_converter.convert_to_uah(price, currency or 'UAH')

                        # Дані для створення/оновлення
                        offer_data = {
                            'ad_id': ad.get('id'),
                            'title': ad.get('title'),
                            'owner_type': business_private,
                            'source': 'OLX',
                            'base_price': base_price,
                            'year_construction': year_of_commissioning,
                            'is_furnished': is_furnished,
                            'price': price,
                            'currency': currency.lower(),
                            'type': property_type or 'apartment',
                            'action': action,
                            'has_phone': has_phone,
                            'no_commission': no_commission,
                            'is_exchange': is_exchange,
                            'cooperate': cooperate,
                            'office_type': office_type,
                            'office_class': office_class,
                            'residential_complex': residential_complex,
                            'city_id': region_obj['city'].get(city_olx_id, {}).get('city_id'),
                            'district_id': district_id,
                            'region_id': region_id,
                            'street': street,
                            'market_type': market_type,
                            'house_number': house_number,
                            'floors': floors,
                            'floor': floor,
                            'total_area': total_area,
                            'kitchen_area': kitchen_area,
                            'cadastral_number': cadastral_number,
                            'rooms': rooms,
                            'landmark': None,
                            'garage_type': garage_type,
                            'land_area': land_area,
                            'from_developer': from_developer,
                            'ad_link': ad.get('url'),
                            'description': ad.get('description'),
                            'main_photo': main_photo,
                            'photos': photos,
                            'ai_owner_probability': None,
                            'street_coordinates': None,

                            'e_oselya': e_oselya,
                            'refresh_time': refresh_time,
                            'property_type_parking': property_type_parking,
                            'appliances': appliances if appliances else None,
                            'bathroom': OLX_TO_DATABASE_MAPPING['bathroom'].get(bathroom) if bathroom else None,
                            'layout': OLX_TO_DATABASE_MAPPING['layout'].get(layout) if layout else None,
                            'heating': OLX_TO_DATABASE_MAPPING['heating'].get(heating) if heating else None,
                            'comfort': comfort if comfort else None,
                            'multimedia': multimedia if multimedia else None,
                            'infrastructure_500_m': infrastructure_500_m if infrastructure_500_m else None,
                            'ecosystem_1_km': ecosystem_1_km if ecosystem_1_km else None,
                            'blackout_autonomy': blackout_autonomy if blackout_autonomy else None,
                            'property_type_appartments_sale': OLX_TO_DATABASE_MAPPING['apartment_type'].get(
                                apartment_type) if apartment_type else None,
                            'comm_re_type': OLX_TO_DATABASE_MAPPING['comm_re_type'].get(
                                comm_re_type) if comm_re_type else None,
                            'repair': OLX_TO_DATABASE_MAPPING['repair'].get(repair_info) if repair_info else None,
                            'property_type_houses': property_type_houses if property_type_houses else None,
                            'property_type_land': property_type_land if property_type_land else None,
                            'communications': communications if communications else None,
                            'is_realtor': 1 if business_private == 'business' else 0

                        }

                        if offer_data.get('type') == 'house' and property_type_houses is None:
                            offer_data['property_type_houses'] = validate_addition_params.detect_property_type_houses(
                                text=offer_data.get('description'))

                        if no_commission is None:
                            offer_data['no_commission'] = validate_addition_params.detect_no_commission(
                                text=offer_data.get('description'))

                        if existing_offer:
                            if existing_offer.get('created_at') < datetime.now() - timedelta(days=6):

                                offer_data['refresh_time'] = datetime.now()

                                offer_data['updated_at'] = datetime.now()
                                offer_data['deleted_at'] = None

                                offer_data.pop('landmark')

                                offer_to_update[ads_id].append(offer_data)
                                logger_main.warning(f'Update ads - {ads_id}')

                                if existing_offer.get('group_id') is None:
                                    if offer_data.get('action') == 'sale' and region_obj['city'].get(city_olx_id, {}).get('detect_photo_duplicates') and offer_data.get(
                                            'type') in ['apartment', 'house']:
                                        await api_send_task({
                                            "ad_id": offer_data.get('ad_id'),
                                            "db_id": existing_offer.get('pk'),  # pk
                                            "action": offer_data.get('action'),
                                            "source": "OLX",
                                            "type_obj": offer_data.get('type'),
                                            "city_id": offer_data.get('city_id'),
                                            "base_price": base_price,
                                            "created_at": int(datetime.now().timestamp())
                                        })
                                        logger_main.info(f'UPDATE ads Send obj to vector service api - {offer_data.get("ad_id")}. db_id = {existing_offer.get("pk")}')
                        else:
                            if offer_data.get('repair') is None:
                                offer_data['repair'] = '1' if await ai_repair.has_repair(
                                    offer_data.get('description')) else None

                            logger_main.warning(f'Add new ads - {ads_id} : {created_at}')
                            # Додаємо часові мітки для нового запису
                            offer_data['created_at'] = created_at
                            offer_data['updated_at'] = updated_at

                            contact_id = None
                            if author_id:
                                if action in ['sale']:
                                    # Отримуємо або створюємо контакт
                                    contact_id = get_or_create_contact(
                                        db=db,
                                        author_id=author_id,
                                        platform='OLX',
                                        is_realtor=1 if business_private == 'business' else 0,
                                        author_name=author_name,
                                        ads_id=ads_id
                                    )

                            # додаєм контакт
                            offer_data['contact_id'] = contact_id

                            call_status = set_call_status(city_id=offer_data.get('city_id'),
                                                          property_type=property_type,
                                                          action=action,
                                                          is_realtor=offer_data['is_realtor']
                                                          )
                            offer_data.update({'call_status': 'new' if call_status else None})

                            # Geocode every listing that carries a street, regardless of
                            # whether the AI enrichment gate below applies to it.
                            offer_data = apply_location(offer_data)

                            # openAi recognize extra parameter
                            if (
                                    (
                                            action == 'sale'
                                        and
                                            region_obj['city'].get(city_olx_id, {}).get('ai_processed')
                                            and property_type in SALE_AI_PROPERTIES_TYPE
                                    )
                                    or (

                                    offer_data.get('city_id') == 10  # тільки Київ
                                    and action == 'rent'  # Оренда
                                    and property_type in RENT_AI_PROPERTIES_TYPE
                            )
                            ):
                                extra_param = await add_extra_params(ad=ad, offer_data=offer_data)
                                offer_data.update(extra_param)

                                if offer_data.get('residential_complex'):

                                    residential_complex_db = rc_lookup.get(offer_data.get('city_id'))
                                    if residential_complex_db:
                                        residential_complex_data = residential_complex_db.get(normalize(offer_data.get('residential_complex')))
                                        if residential_complex_data:
                                            offer_data['residential_complex'] = residential_complex_data.get("origin")
                                            offer_data['housing_complex_id'] = residential_complex_data.get("id")
                                            logger_main.info(f'🏘Set residential_complex - {residential_complex_data.get("origin")} with id { residential_complex_data.get("id")}')
                                        # else:
                                        #     offer_data.pop('residential_complex')

                            offer_to_create.append(offer_data)
                            new_rows.append(1)

                            stats.total_new += 1
                except Exception as ex:
                    logger_main.warning(f'Parsing ads error - {ex}')

            return True
    except Exception as ex:
        logger_main.warning(f'Extract data error - {ex}')
        return False

    finally:

        # batch update offers
        if offer_to_update:
            models.Offer.bulk_update_offers(offers_to_update=offer_to_update)
            logger_main.info(f'Update {len(offer_to_update)}')
        else:
            logger_main.info(f'Not new offers to update')

        # batch create offers
        if offer_to_create:
            result = models.Offer.bulk_create_offers(offers_data=offer_to_create)
            logger_main.info(f'Result created offer: - {result}')

            # batch create new log ads
            models.OfferLog.batch_create_logs(log_new_ads=result.get('created_offer_ids', []))
            for offer in offer_to_create:
                try:

                    if offer.get('action') == 'sale' and region_obj['city'].get(offer.get('city_id'), {}).get('detect_photo_duplicates')\
                            and offer.get('type') in ['apartment', 'house']:

                        db_id = result.get('created_ad_ids', {}).get(offer.get('ad_id'))
                        await api_send_task({
                                    "ad_id": offer.get('ad_id'),
                                     "db_id": db_id, # pk
                                      "action": offer.get('action'),
                                       "source": "OLX",
                                        "type_obj": offer.get('type'),
                                         "city_id": offer.get('city_id'),
                                          "base_price": offer.get('base_price'),
                                           "created_at": int(datetime.now().timestamp())
                                })
                        logger_main.info(f'Send obj to vector service api - {offer.get("ad_id")}. db_id = {db_id}')
                except:
                    pass
        else:
            logger_main.info(f'Not new offers to create')

        logger_main.info(f'Success complete batch...')


async def process_city(region_obj: dict, rc_lookup: dict):
    region_olx_id = region_obj.get('region_olx_id')
    region_id = region_obj.get('region_id')
    links = []

    try:

        with requests.Session(impersonate=IMPERSONATE) as session:
            for categories_id, name in settings.ALLOWED_CATEGORIES.items():
                try:
                    currency = 'USD' if 'Продаж' in name else 'UAH'
                    action = 'sale' if 'Продаж' in name else 'rent'
                    links = utils.generate_links_list_monitoring(region_olx_id=region_olx_id,
                                                                 categories_id=categories_id,
                                                                 currency=currency)

                    tasks = []
                    for private_link in links:
                        tasks.append(extract_data(url=private_link,
                                                  region_obj=region_obj,
                                                  name_category=name,
                                                  action=action,
                                                  rc_lookup=rc_lookup,
                                                  region_id=region_id,
                                                  session=session))

                    if tasks:
                        print(f'Try run {len(tasks)} tasks...')
                        await asyncio.gather(*tasks)
                except Exception as ex:
                    logger_main.warning(f'* Error execute - ex:{ex}. links: {links}*')

    except Exception as ex:
        logger_main.warning(f'* Error region: {region_id} - ex:{ex} . links: {links}*')


async def start_parsing_olx(regions):
    start = datetime.now()
    logger_main.info(f'Start parser - {datetime.now()}')

    # Список ЖК
    rc_lookup = build_rc_lookup()

    # Створюємо список задач для всіх міст
    for _, region_obj in regions.items():
        await process_city(region_obj=region_obj, rc_lookup=rc_lookup)

    finish = datetime.now() - start
    logger_main.info(f'Finish parser - {datetime.now()}. Work at {finish} ')


async def main_loop():
        regions = models.Region.get_all_cities_from_parsing_regions(country_id=1) # Ukraine

    # while True:
        try:
            print(f'Start pars... Use proxy: {settings.PROXY}')

            # Update currency exchange rates at the start of each parsing cycle
            logger_main.info("Updating currency exchange rates...")
            await currency_converter.update_exchange_rates()

            stats.total_new = 0

            await start_parsing_olx(regions=regions)
            logger_main.info(
                f'ADD new ads {stats.total_new}.\nSleeping for 5 minutes seconds before next parsing cycle')

        except Exception as e:
            logger_main.error(f'Critical error in main loop: {str(e)}')
            logger_main.info(f'Sleeping for 60 seconds after error before retrying')
            # await asyncio.sleep(60)


if __name__ == '__main__':
    try:
        logger_main.info("Starting continuous monitoring service")
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger_main.info("Service manually stopped")
    except Exception as e:
        logger_main.error(f"Fatal error: {str(e)}")
