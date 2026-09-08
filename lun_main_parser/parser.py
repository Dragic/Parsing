import asyncio
import logging
import time
import re
import aiohttp
import requests
from settings import settings
import json
import ai_repair
from vector_service import api_send_task
import validate_addition_params
from bs4 import BeautifulSoup
from config import headers
import models
from currency_api import currency_converter
from log import logger
from database import db_session
from datetime import datetime, timedelta
import re

logger_parser = logging.getLogger('log.lunua_parser.py')


TYPE_MAP = {
    "land": "land",
    "apartment": "flats",
    "house": "houses",

}

URLS = [
    ("sale", "land"),
    ("sale", "apartment"),
    ("sale", "house"),
    ("rent", "apartment"),
    ("rent", "house"),

]


def extract_json_from_push(text: str) -> dict:
    match = re.search(r'self\.__next_f\.push\(\[1,"(.+)"\]\)', text, re.DOTALL)
    if not match:
        return {}

    raw = match.group(1)

    try:
        # raw - це вміст JS-рядка, тому декодуємо його як JSON-рядок
        # (коректно розкриває \", \\, \n тощо)
        content = json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        content = raw.replace('\\"', '"').replace('\\\\', '\\')

    # Весь next_f.push тепер може містити декілька RSC-чанків, злитих в один
    # рядок, тому шукаємо саме значення ключа "realties" через пошук балансу
    # дужок, а не жадібний regex по всьому тексту.
    key = '"realties":'
    key_idx = content.find(key)
    if key_idx == -1:
        return {}

    start = key_idx + len(key)
    depth = 0
    in_string = False
    escape = False
    end = None
    for i in range(start, len(content)):
        ch = content[i]
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end is None:
        return {}

    try:
        return {'realties': json.loads(content[start:end])}
    except json.JSONDecodeError:
        return {}


# kiev district
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

def generate_title(data: dict, action: str, property_type_land) -> str:
    try:

        rooms = data.get('roomCount')
        area = data.get('areaTotal')
        floor = data.get('floor')
        floor_count = data.get('floorCount')

        action_str = 'Оренда' if action == 'rent' else 'Продаж'

        if property_type_land:
            return f'{action_str}. Ділянка - {property_type_land}'

        rooms_str = f'{rooms}-кімн.' if rooms else 'Студія'

        parts = [action_str, 'квартири', rooms_str]

        if area:
            parts.append(f'{area} м²')

        if floor and floor_count:
            parts.append(f'{floor}/{floor_count} пов.')

        return ' '.join(parts)
    except Exception as ex:
        print(ex)
        logger_parser.warning(f'Error generate title - {ex}. action: {action}. property_type_land: {property_type_land}. data: {data}')
        return f'{action}'


def parse_lun_cards(html: str) -> dict:
    soup = BeautifulSoup(html, 'html.parser')

    result = {}

    cards = soup.find_all(class_=re.compile(r'RealtyCard-module-scss-module__\w+__root'))

    for card in cards:
        # ID
        try:
            ad_id = None
            event_el = card.find(attrs={'data-event-options': re.compile(r'page_id:')})
            if event_el:
                options = event_el.get('data-event-options', '')
                match = re.search(r'page_id:(\d+)', options)
                if match:
                    ad_id = int(match.group(1))

            # Опис
            description_el = card.find(class_=re.compile(r'RealtyCard-module-scss-module__\w+__description\b'))
            description = description_el.get_text(strip=True) if description_el else None

            if ad_id:
                result[str(ad_id)] = description
        except Exception as ex:
            print(f'error card - {ex}')

    return result

def land_type(value: str|None) -> int | None:
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

async def parse_lun_offer(data: dict) -> dict:
    # Геодані
    city_name = None
    street = None
    house_number = None
    district = None
    lun_id = None
    residential_complex = None
    property_type_land = None

    for geo in data.get('geoEntities', []):
        geo_type = geo.get('type')
        if geo_type == 'city':
            city_name = geo.get('name')
            lun_id = geo.get('geoId')

        elif geo_type == 'district':
            district = geo.get('name')
        elif geo_type == 'residential_complex':
            residential_complex = geo.get('name')
        elif geo_type == 'street':
            street = geo.get('name')
        elif geo_type == 'house':
            house_number = geo.get('name')

    # Фото
    images = []
    for img in data.get('images', []):
        image_id = img.get('imageId')
        if image_id:
            images.append(f"https://market-images.lunstatic.net/lun-ua/840/1492/images/{image_id}.webp")

    main_photo = images[0] if images else None

    # Локація
    location = data.get('location')
    longitude = None
    latitude = None
    if location and len(location) > 1:
        latitude = location[1]
        longitude = location[0]

    # Контакт
    contact = data.get('rieltorContact', {}) or {}
    is_realtor = contact.get('contactType') != 'owner'

    # Тип секції → action
    e_oselya = data.get('hasEoselia')

    land_area = data.get('areaLand')
    try:
        aim = data.get('aim', [])
        for type_aim in aim:
            if type_aim.get('name', '').lower() in ['під забудову', 'сільгосппризначення', 'промпризначення', 'комерційного призначення']:
                property_type_land = land_type(f"{type_aim.get('name', '')}".lower())
                break
    except:
        pass

    section_id = data.get('sectionId')
    action = 'rent' if section_id == 2 else 'sale'

    # Автор
    phones = contact.get('phones') or data.get('phones') or []
    phone = phones[0] if phones else None
    base_price = 0
    if data.get('price') is not None:
        base_price = await currency_converter.convert_to_uah(data.get('price'),  (data.get('currency') or 'uah').upper() or 'UAH')

    offer_data = {
        'name': contact.get('name'),
        'phone': f'+{phone}' if phone else None,
        'avatar': contact.get('avatar'),
        'e_oselya': e_oselya,
        'living_area': data.get('areaLiving'),
        'property_type_land': property_type_land,
        'city_name': city_name,
        'district': district,

        'ad_id': data.get('id'),
        'title': generate_title(data=data, action='Продаж' if action == 'sale' else 'Оренда', property_type_land=property_type_land),
        'owner_type': 'business' if is_realtor else 'private',
        'source': 'LUNUA',
        'lun_id': lun_id,
        'land_area': land_area,

        'price': data.get('price'),
        'base_price': base_price,
        'currency': (data.get('currency') or 'uah').lower(),

        'action': action,
        'is_realtor': is_realtor,
        'no_commission': data.get('withoutCommission', False),
        'street': street if street and len(f"{street}") >= 4 else None,
        'house_number': house_number if street else None,
        'floors': data.get('floorCount'),
        'floor': data.get('floor'),
        'total_area': data.get('areaTotal'),
        'kitchen_area': data.get('areaKitchen'),
        'rooms': data.get('roomCount'),
        'updated_at': datetime.utcnow(),
        'latitude': latitude,
        'longitude': longitude,
        'ad_link': f"https://lun.ua/realty/{data.get('id')}",
        'description': data.get('text'),
        'main_photo': main_photo,
        'photos': images,
        'refresh_time': datetime.utcnow(),
        'created_at': datetime.utcnow(),
        'residential_complex': residential_complex,
        'from_developer': False,
    }

    return offer_data


def exist_contact(db, author_id, platform='LUNUA'):
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


def create_contact(db, author_id, author_link, is_realtor, author_name, phone, platform='LUNUA'):
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


async def get_new_data(*, session, obj_data):
    try:
        async with session.get(url=obj_data.get('url'), proxy=settings.PROXY, headers=headers) as response:
            text = await response.text()

        pattern = r"site:lun\.ua\|page_id:(\d+)"

        page_ids = re.findall(pattern, text)
        print(page_ids)
        current_ids = list(set(page_ids))

        ids = models.Offer.get_offers_created_at(ad_ids=current_ids, source='LUNUA')
        soup = BeautifulSoup(text, 'html.parser')
        description_dict = parse_lun_cards(text)
        scripts = soup.find_all('script')
        for script in scripts:
                    if 'bankId' in script.text:
                        print('bakd - OK')
                        data = extract_json_from_push(script.text)
                        print(data)
                        cards = data.get('realties', {}).get('cards')
                        for card in cards:
                            offer_data = {}
                            try:
                                urlRaw = card.get('urlRaw')
                                if 'lun.ua' in urlRaw and int(card.get('id')) not in ids:
                                    print('Get card -', int(card.get('id')))

                                    offer_data = await parse_lun_offer(card)

                                    lun_id = offer_data.get('lun_id')
                                    city_id = obj_data.get('cities', {}).get(lun_id, {}).get("id")
                                    region_id = obj_data.get('cities', {}).get(lun_id, {}).get("region_id")
                                    if lun_id is None or city_id is None or region_id is None:
                                        logger_parser.warning(f'❗️️️🏘️️️geoId = {lun_id}. ️City not found - {offer_data.get("city_name")}. {offer_data.get("ad_link")}')
                                        continue

                                    offer_data['type'] = obj_data.get('type')
                                    offer_data['action'] = obj_data.get('action')
                                    offer_data['description'] = description_dict.get(str(card.get('id')))

                                    offer_data['city_id'] = city_id
                                    offer_data['region_id'] = region_id

                                    print(f'OFFERS: {offer_data}')

                                    if offer_data.get('action') == 'sale':
                                        offer_data['repair'] = '1' if await ai_repair.has_repair(
                                            offer_data.get('description')) else None

                                    if offer_data.get('type') == 'house':
                                        offer_data[
                                            'property_type_houses'] = validate_addition_params.detect_property_type_houses(
                                            text=offer_data.get('description'))

                                    offer_data['no_commission'] = validate_addition_params.detect_no_commission(
                                        text=offer_data.get('description'))

                                    with db_session() as db:

                                        author_id = offer_data.get('phone', '').replace('+', '')[3:]

                                        contact_id = exist_contact(
                                            db=db,
                                            author_id=author_id
                                        )

                                        if not contact_id:
                                            contact_id = create_contact(db=db,
                                                                        author_id=author_id,
                                                                        author_link=None,
                                                                        is_realtor=1 if offer_data.get('is_realtor') else 0,
                                                                        phone=offer_data.get('phone'),
                                                                        author_name=offer_data.get('name'))
                                            offer_data['contact_id'] = contact_id
                                        else:
                                            offer_data['contact_id'] = contact_id

                                        # only for Kyiv
                                        if str(city_id) == str(10) and offer_data.get('district'):
                                            offer_data['district_id'] = district_pars(offer_data.get('district'))

                                        offer_data.pop('city_name')
                                        offer_data.pop('lun_id')
                                        offer_data.pop('avatar')
                                        offer_data.pop('phone')
                                        offer_data.pop('name')
                                        offer_data.pop('district')
                                        base_price = offer_data.pop('base_price')

                                        raw_offer = models.Offer(**offer_data)
                                        db.add(raw_offer)
                                        db.commit()
                                        db.refresh(raw_offer)
                                        logger_parser.warning(f'Create new ads - {offer_data.get("ad_link")}')

                                        if offer_data.get('action') == 'sale' and offer_data.get(
                                            'type') in ['apartment', 'house']:

                                            if obj_data.get('cities', {}).get(lun_id, {}).get(
                                                    'detect_photo_duplicates'):

                                                await api_send_task({
                                                    "ad_id": offer_data.get('ad_id'),
                                                    "db_id": raw_offer.id,  # pk
                                                    "action": offer_data.get('action'),
                                                    "source": "LUNUA",
                                                    "type_obj": offer_data.get('type'),
                                                    "city_id": offer_data.get('city_id'),
                                                    "base_price": base_price,
                                                    "created_at": int(datetime.utcnow().timestamp())
                                                })
                                                logger_parser.info(
                                                    f'Send obj to vector service api - {offer_data.get("ad_id")}. db_id = {raw_offer.id}')

                            except Exception as er:
                                logger_parser.warning(f'during parser ex {er} - ads id: {offer_data}')

    except Exception as ex:
        logger_parser.warning(f'ПОМИЛКА ПАРСИНГУ {ex}')


async def task_watch():
    print(f"start task {datetime.now()}")

    await currency_converter.update_exchange_rates()
    cities = models.City.get_active_lun_cities()

    try:
        async with aiohttp.ClientSession() as session:
            urls = []

            for action, obj_type in URLS:
                url = (
                    f"https://lun.ua/"
                    f"{action}/"
                    f"kyiv/"
                    f"{TYPE_MAP[obj_type]}"
                    f"?geoDistance=10009580%3A1000000"
                    f"&sort=insert_time"
                )

                if obj_type != "land":
                    url += "&without_broker=owner"

                urls.append(
                    {
                        "url": url,
                        "cities": cities,
                        "type": obj_type,
                        "action": action,
                    }
                )

            for page in range(1, 6):
                for obj_data in urls:
                    obj = obj_data.copy()
                    obj["url"] = f"{obj['url']}&page={page}"

                    await get_new_data(
                        session=session,
                        obj_data=obj,
                    )

    except Exception as ex:
        logger_parser.warning(f"task_watch - {ex}")
    print(f"end task {datetime.now()}")


if __name__ == '__main__':
    asyncio.run(task_watch())
