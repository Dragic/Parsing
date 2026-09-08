import asyncio
from collections import defaultdict

import requests

from vector_service import api_send_task
from settings import settings
from log import logger
import logging
import models
import time
import ai_repair
import re
import validate_addition_params
import ai_agent
import location_api
from database import db_session
import aiohttp
from datetime import datetime, timedelta
from currency_api import currency_converter
from utils import SimpleTTLCache, metro_stations

# init cache
ads_search_cache = SimpleTTLCache()

logg = logging.getLogger('log.ria_parser.py')

# Семафор для обмеження кількості одночасних запитів
SEMAPHORE = asyncio.Semaphore(1)

REALTORS_CACHE = {}

REALTORS_LOCK = asyncio.Lock()

# AI additions params recognize
SALE_AI_PROPERTIES_TYPE = ['apartment', 'house', 'commercial']
RENT_AI_PROPERTIES_TYPE = ['apartment', 'house', 'commercial']


def land_type(characteristics_values: dict) -> int | None:
    """
    key 2099 - цільове призначення
    :param dict:
    :return:
    """
    value = characteristics_values.get('2099')

    if value is None:
        return None

    # characteristics_values key  = 2099
    # 2083 - під житлову забудову
    # 2094 - Індивідуального садівництва
    # 2082 - сільськогосподарське
    # 2091 - Промисловості
    # 2086 - Оздоровче
    # 2098 - Загального користування
    # 2087 - Рекреаційне
    # 2092 - Транспортне
    # 2084 - Під громадську забудову
    # 2095 - Ведення особистого селянського господарства

    property_type_land = {
        "2095": "1",
        "2082": "1",

        "2084": "2",
        "2083": "2",

        '2086': "3",
        '2087': "4",

        '2091': "7",
        '2092': "7",
        '2098': "8",
        '2094': "8"
    }
    return property_type_land.get(f'{value}')


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


async def is_realtor_in_cache(user_id, platform):
    """Перевіряє, чи є рієлтор у глобальному кеші"""
    async with REALTORS_LOCK:
        return (user_id, platform) in REALTORS_CACHE


async def add_realtor_to_cache(user_id, platform):
    """Додає рієлтора до глобального кешу"""
    async with REALTORS_LOCK:
        REALTORS_CACHE[(user_id, platform)] = True


async def clear_realtors_cache():
    """Очищує глобальний кеш рієлторів"""
    async with REALTORS_LOCK:
        REALTORS_CACHE.clear()
        logg.info(f"Cleared realtors cache")


def exist_contact(db, author_id, platform='DOMRIA'):

    if not author_id:
        return None

    # Шукаємо існуючий контакт
    existing_contact = db.query(models.ContactPlatform).filter(
        models.ContactPlatform.user_id == author_id,
        models.ContactPlatform.platform == platform
    ).first()

    if existing_contact:
        return existing_contact.contact_id
    return None


def verify_link(url):
    try:
        response = requests.get(url=url, headers=settings.HEADERS, timeout=10)
        if response.status_code > 300:
            return None
        return url
    except:
        return None

def create_contact(db, author_id, is_realtor, author_name, phone, platform='DOMRIA'):
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
            link=f'https://dom.ria.com/uk/realtor-{author_id}.html'
        )
        db.add(platform_contact)
        db.commit()
        return existing_contact.id
    else:

        str_autor = f'{author_id}'
        author_link_verify = verify_link(f"https://cdn.riastatic.com/photos/avatars/all/{str_autor[0:4]}/{str_autor[:-2]}/{author_id}/{author_id}xxb.jpg")
        # Створюємо новий контакт
        new_contact = models.ContactNew(
            phone=phone,
            name=author_name,
            avatar=author_link_verify,
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
            link=f'https://dom.ria.com/uk/realtor-{author_id}.html'
        )
        db.add(platform_contact)
        db.commit()

        return new_contact.id


async def get_phone(session, hash: str):
    try:
        async with session.get(f'https://dom.ria.com/v1/api/realty/getOwnerAndAgencyData/{hash}?spa_final_page=true',
                               timeout=15, headers=settings.HEADERS) as response:

            data = await response.json()
            phone = data['owner']['phones'][0]['phone_num']
        return f"+38{phone.replace('(', '').replace(')', '').replace(' ', '').strip()}"
    except Exception as ex:
        logg.warning(f'Error during extract phone - {hash}.Error {ex}.')
        return None



async def get_ads_list(session, search: str, page='') -> list:
    try:
        search = search.split('?')[-1]
        new_ads = []

        async with session.get(
                f'https://dom.ria.com/node/searchEngine/v2/?{search}{page}',
                timeout=15,
                headers=settings.HEADERS
        ) as response:
            if response.status > 200:
                logg.warning(f'Sleep 20 sec. Response: {response.status}. Url: {search} ')
                time.sleep(20)
                return []

            data = await response.json()


            # Фільтрація елементів через кеш
            result = ads_search_cache.filter_new_items(f"{search}_key", data["items"])

            if len(result) > 0:
                new_obj = models.Offer.get_offers_created_at_full(ad_ids=result, source='DOMRIA')
                for k, v in new_obj.items():
                    if v is None:
                        new_ads.append(k)
                return new_ads

            return []
    except Exception as ex:
        logg.warning(f'get_ads_list - {ex}. URL: {search}')
        return []

# for many pages
async def pages_get_ads_list(session, search: str) -> list:
    try:
        search = search.split('?')[-1]
        new_ads = []

        for page in range(1, 16):

            async with session.get(
                f'https://dom.ria.com/node/searchEngine/v2/?{search}&page={page}',
                timeout=15,
                headers=settings.HEADERS
            ) as response:

                if response.status > 200:
                    logg.warning(f'Sleep 20 sec. Response: {response.status}. Url: {search} page={page}')
                    time.sleep(20)
                    continue

                data = await response.json()

                if not data.get("items"):
                    break

                # фільтр через кеш
                result = ads_search_cache.filter_new_items(search, data["items"])

                if len(result) > 0:
                    new_obj = models.Offer.get_offers_created_at(ad_ids=result, source='DOMRIA')

                    for k, v in new_obj.items():
                        if v is None:
                            new_ads.append(k)

        return new_ads

    except Exception as ex:
        logg.warning(f'get_ads_list - {ex}. URL: {search}')
        return []


async def extract_data(ad_id: str,  action: str, property_type: str,
                       region_obj: dict, rc_lookup: dict, session) -> bool:
    try:
        async with SEMAPHORE:
            async with session.get(f'https://dom.ria.com/v1/api/realty/final/{ad_id}',
                                   timeout=15, headers=settings.HEADERS) as response:
                logg.info(f'{ad_id} - {response.status}')

                if response.status > 201:
                    logg.warning(f'Response: {response.status}. Url: {ad_id} ')
                    return True

                data = await response.json()

                ads_url = f"https://dom.ria.com/uk/{data['realty']['beautiful_url']}"

                description = data['realty'].get("description_uk", '').replace(r'\r', '')
                if description == '':
                    description = data['realty'].get("description", '').replace(r'\r', '')


                city_id = data['realty']['city_id']
                city_obj = region_obj['cities'].get(city_id)
                if city_obj is None:
                    # logg.warning(f'City not found in list cities parsing - {city_id}. ad_id {ad_id}')
                    return False

                author_id = data['realty']['user_id']
                author_name = data['agencyOwner']['owner'].get('name', '-')
                user_hash = data['hash']

                # Формування координат
                latitude = None
                longitude = None
                if data['realty'].get('longitude', None):
                    latitude = data['realty'].get('latitude', None)
                    longitude = data['realty'].get('longitude', None)

                street = data['realty'].get('street_name_uk', None)

                map_position = location_api.get_location(
                    city_id=city_id,
                    street=street
                )
                microdistrict_id = map_position.get('microdistrict_id')
                if map_position.get('street'):
                    street = map_position.get('street')

                if map_position.get('lat') and map_position.get('lon'):
                    latitude = map_position.get('lat')
                    longitude = map_position.get('lon')

                house_number = data['realty'].get('building_number_str', None)
                year_construction = None

                residential_complex = data.get('user_newbuild_name', None)

                # Отримання ціни
                price = data['realty']['price']

                currency_pars = data['realty'].get('currency_type', 'UAH')
                if currency_pars in ['$']:
                    currency = 'USD'
                elif currency_pars in ['€']:
                    currency = 'EUR'
                else:
                    currency = 'UAH'

                # Calculate base_price in UAH
                base_price = 0
                if price is not None:
                    base_price = await currency_converter.convert_to_uah(price, currency or 'UAH')

                # Кількість кімнат
                rooms = data['realty'].get('rooms_count', None)

                # Загальна площа
                total_area = data['realty'].get('total_square_meters', None)
                subway_id = metro_stations.get(data['realty'].get('metro_station_id', None), {}).get('db_id')

                kitchen_area = data['realty'].get('kitchen_square_meters', None)

                if total_area is None:
                    # для ділянок
                    total_area = data['realty'].get('ares_count', None)

                # Поверховість
                floor = data['realty'].get('floor', None)
                floors = data['realty'].get('floors_count', None)

                # Фото
                photos = []
                main_photo = None
                images = data['realty']['photos']
                base_img_url = 'https://cdn.riastatic.com/photosnew/'

                for count, photo in enumerate(images, start=1):
                    url_p = photo['beautifulUrl'].replace(".jpg", 'xl.jpg')
                    img_link = f"{base_img_url}{url_p}"
                    if count == 1:
                        photo_m = 'https://cdn.riastatic.com/photos/' + photo.get('file', '').replace('.jpg', 'fm.webp')
                        main_photo = photo_m

                    photos.append(img_link)

                # Перевірка на поля e_oselya
                e_oselya_status = data['realty'].get('characteristics_values', {}).get("201", 0)
                e_oselya = 1 if e_oselya_status else 0

                # Перевірка no_commission
                no_commission_data = data['realty'].get('characteristics_values', {}).get("2021", False)
                no_commission = True if no_commission_data else False

                # Визначення дати оновлення/створення
                created_at = datetime.now()
                updated_at = None
                refresh_time = None
                district_id = None

                property_type_land = land_type(data['realty'].get('characteristics_values', {}))

                main_characteristics = data['realty'].get('mainCharacteristics', {}).get('chars', [])
                for char in main_characteristics:
                    if char.get('charId') == 443:
                        try:
                            match = re.search(r'\b(19|20)\d{2}\b', char.get('value', [])[0])
                            year = int(match.group()) if match else None

                            year_construction = year
                        except Exception as e:
                            logg.warning(f'Error year_construction pars - {e}. Chars - {char}')

                districts = city_obj.get('districts', {})
                ria_district_id = data['realty'].get('district_id')
                if ria_district_id:
                    parent_id = districts.get(ria_district_id)
                    logg.info(f'ad_id: {ad_id}. parent_id: {parent_id}. ria_district_id: {ria_district_id}')
                    district_id = parent_id if parent_id else ria_district_id if ria_district_id in districts else None

                try:
                    refresh_time = datetime.fromisoformat(data['realty']['updated_at'])
                    updated_at = refresh_time
                except (ValueError, TypeError):
                    pass

                living_area = data['realty'].get('living_square_meters', None)
                is_e_vidnovlennia = bool(data['realty'].get('characteristics_values', {}).get("2064", False))

                repair = None
                if action == 'sale':
                    repair = '1' if await ai_repair.has_repair(description) else None

                    market_type = 'secondary' if 'Вторичное жилье' in data['realty'].get('mainCharacteristics', {}).get('dashes', []) else 'primary'
                else:
                    market_type = 'secondary'

                business_private = 'business' if data['realty']['is_commercial'] == 1 else 'private'
                title = data['realty']['advert_type_name_uk'].title() + ' ' + data['realty'].get('realty_type_name_uk',
                                                                                                 '') + ' ' + data[
                            'realty'].get('district_name_uk', ''),

                property_type_houses = None
                if data['realty'].get('realty_type_name_uk') == 'Таунхаус' or 'таунхаус' in description.lower():
                    property_type_houses = 'townhouse'

                if property_type == 'house' and property_type_houses is None:
                    property_type_houses = validate_addition_params.detect_property_type_houses(text=description)

                with db_session() as db:
                    # Дані для створення/оновлення
                    offer_data = {
                        'ad_id': ad_id,
                        'repair': repair,
                        'property_type_houses': property_type_houses,
                        'title': title,
                        'owner_type': business_private,
                        'source': 'DOMRIA',
                        'price': price,
                        'microdistrict_id': microdistrict_id,
                        'year_construction': year_construction,
                        'subway_id': subway_id,
                        'currency': currency.lower() or 'uah',
                        'type': property_type,
                        'property_type_land': property_type_land,
                        'action': action,
                        'no_commission': no_commission,
                        'market_type': market_type,
                        'residential_complex': residential_complex,
                        'city_id': city_id,
                        'district_id': district_id,
                        'living_area': living_area,
                        'is_e_vidnovlennia': is_e_vidnovlennia,
                        'region_id': region_obj.get('region_id'),
                        'street': street,
                        'house_number': house_number,
                        'floors': floors,
                        'floor': floor,
                        'total_area': total_area,
                        'kitchen_area': kitchen_area,
                        'rooms': rooms,
                        'updated_at': updated_at,
                        'latitude': latitude,
                        'longitude': longitude,
                        'landmark': None,
                        'ad_link': ads_url,
                        'description': description,
                        'main_photo': main_photo,
                        'photos': photos,
                        'e_oselya': e_oselya,
                        'refresh_time': refresh_time,
                        'created_at': created_at,
                    }

                    contact_id = None
                    if author_id:
                        # Отримуємо або створюємо контакт
                        contact_id = exist_contact(
                            db=db,
                            author_id=author_id
                        ) # перевіряємо в платормах чи є контакт, якщо немає то створюємо в контактах і платформах

                        if contact_id is None:
                            await add_realtor_to_cache(author_id, 'DOMRIA')
                            phone = await get_phone(session=session, hash=user_hash)
                            if phone is not None:
                                contact_id = create_contact(db=db,
                                                            author_id=author_id,
                                                            phone=phone,
                                                            is_realtor=1 if business_private == 'business' else 0,
                                                            author_name=author_name)

                    offer_data['contact_id'] = contact_id

                    offer_data['is_realtor'] = 0

                    if business_private == 'business':
                        offer_data['is_realtor'] = 1

                    if (
                            (
                                    action == 'sale'
                                    and
                                    region_obj['cities'].get(city_id, {}).get('ai_processed')
                                    and property_type in SALE_AI_PROPERTIES_TYPE
                            )
                            or (

                            offer_data.get('city_id') == 10  # тільки Київ
                            and action == 'rent'  # Оренда
                            and property_type in RENT_AI_PROPERTIES_TYPE
                    )
                    ):
                        # ai reach offer params
                        if str(offer_data.get('city_id')) == str(10): # Київ
                            missing_fields = [f for f in ai_agent.AI_EXTRACTABLE_FIELDS_KYIV if not offer_data.get(f)]
                        else:
                            missing_fields = [f for f in ai_agent.AI_EXTRACTABLE_FIELDS_REGION if not offer_data.get(f)]

                        if missing_fields:
                            ai_result = await ai_agent.addition_params(
                                version=settings.PROMPT_VERSION,
                                prompt_id=settings.PROMPT_ID,
                                input_msg=f'Знайди цей перелік полів:{missing_fields}\n\n{offer_data.get("title")}\n'
                                          f'Опис: {offer_data.get("description")} {residential_complex}\n'
                            )

                            if ai_result:
                                for field in missing_fields:
                                    ai_value = ai_result.get(field)
                                    if ai_value is not None:
                                        if offer_data.get(field) is None:
                                            offer_data[field] = ai_value
                                            logg.warning(
                                                f'🟩️️️️️️AI recognize ad_id: {ad_id}. Set extra params field {field}: {ai_value}')

                    if offer_data.get('residential_complex'):

                        residential_complex_db = rc_lookup.get(offer_data.get('city_id'))
                        if residential_complex_db:
                            residential_complex_data = residential_complex_db.get(
                                normalize(offer_data.get('residential_complex')))
                            if residential_complex_data:
                                offer_data['residential_complex'] = residential_complex_data.get("origin")
                                offer_data['housing_complex_id'] = residential_complex_data.get("id")
                                logg.info(
                                    f'🏘Set residential_complex - {residential_complex_data.get("origin")} with id {residential_complex_data.get("id")}')

                    raw_offer = models.Offer(**offer_data)
                    db.add(raw_offer)
                    db.commit()
                    db.refresh(raw_offer)

                    logg.info(f'Create new offer - {ad_id}')

                    if offer_data.get('action') == 'sale' and region_obj['cities'].get(city_id, {}).get(
                            'detect_photo_duplicates') and offer_data.get(
                            'type') in ['apartment', 'house']:

                        await api_send_task({
                            "ad_id": offer_data.get('ad_id'),
                            "db_id": raw_offer.id,  # pk
                            "action": offer_data.get('action'),
                            "source": "DOMRIA",
                            "type_obj": offer_data.get('type'),
                            "city_id": offer_data.get('city_id'),
                            "base_price": base_price,
                            "created_at": int(datetime.now().timestamp())
                        })
                        logg.info(f'Send obj to vector service api - {offer_data.get("ad_id")}. db_id = {raw_offer.id}')

                return True

    except Exception as ex:
        logg.warning(f'Error during create obj {ad_id}. EX: {ex}.{data}')
        return False

# Глобальний, спільний для всього запуску набір вже оброблених ads_id.
# Множина в asyncio безпечна без locks, поки перевірка+додавання
# не розривається await'ом (тут це так, це синхронний код).
processed_ads_ids: set[str] = set()


async def process_city(region_obj: dict, rc_lookup: dict, processed_ads_ids: set):
    try:
        logg.info(f'Start region - {region_obj.get("region_name")}')
        region_id = region_obj.get('region_id')
        obj_links = settings.RIA_OBJ_URL

        async with aiohttp.ClientSession() as session:
            for action in obj_links:
                for type_obj, list_url in obj_links[action].items():
                    for url in list_url:
                        ads_ids = await get_ads_list(session=session,
                                                     search=url.replace('RIA_STATE_ID', f'{region_id}'))

                        # Фільтруємо ті ads_id, що вже були оброблені раніше (глобально)
                        new_ads_ids = []
                        for ad_id in ads_ids:
                            if ad_id in processed_ads_ids:
                                continue
                            processed_ads_ids.add(ad_id)
                            new_ads_ids.append(ad_id)

                        skipped = len(ads_ids) - len(new_ads_ids)
                        if skipped:
                            logg.info(
                                f'{region_obj.get("region_name")} / {action}/{type_obj}: '
                                f'skipped {skipped} duplicate ads_id, {len(new_ads_ids)} new'
                            )

                        if not new_ads_ids:
                            continue

                        # pars private ads
                        tasks = [extract_data(ad_id=ad_id,
                                              property_type=type_obj,
                                              action=action,
                                              rc_lookup=rc_lookup,
                                              region_obj=region_obj,
                                              session=session) for ad_id in new_ads_ids]
                        await asyncio.gather(*tasks)

    except Exception as ex:
        logg.warning(f'* Error region parsing: {region_obj.get("region_name")} - ex:{ex} *')


async def start_parsing_ria(regions: dict):
    start = datetime.now()
    logg.info(f'Start parser - {datetime.now()}')
    processed_ads_ids = set()

    rc_lookup = build_rc_lookup()
    # clear cache
    await clear_realtors_cache()

    for region_id, region_obj in regions.items():
        await process_city(region_obj, rc_lookup, processed_ads_ids)

    # clear cache
    await clear_realtors_cache()

    finish = datetime.now() - start
    logg.info(f'Finish parser - {datetime.now()}. Work at {finish} ')


async def main_loop():
        regions = models.Region.get_all_cities_from_parsing_regions_domria(country_id=1)  # Ukraine
    # while True:
        try:
            await start_parsing_ria(regions=regions)

            await currency_converter.update_exchange_rates()
            logg.info(f'Sleeping for 30 seconds before next parsing cycle')

            # поточний UTC час
            # how_hour = datetime.utcnow().hour
            #
            # if how_hour in [x for x in range(4, 23)]:
            #     await asyncio.sleep(60*3)  # sleep seconds
            # else:
            #     await asyncio.sleep(60 * 5)

        except Exception as e:
            logg.error(f'Critical error in main loop: {str(e)}')
            logg.info(f'Sleeping for 60 seconds after error before retrying')
            # await asyncio.sleep(60)


if __name__ == '__main__':
    try:
        logg.info("Starting continuous monitoring service")
        asyncio.run(main_loop())
        logg.info("Finish continuous monitoring service")
    except KeyboardInterrupt:
        logg.info("Service manually stopped")
    except Exception as e:
        logg.error(f"Fatal error: {str(e)}")
