import requests
from bs4 import BeautifulSoup
from settings import settings
import config
import json
import re
from datetime import datetime


def parse_address(text: str):
    import re

    # Видаляємо зайві прошаки
    text = text.strip()

    # Розширений регулярний вираз для розбору адреси
    match = re.match(
        r'^(.*?)\s*(?:Ул\.|Вул\.|Улица|Вулиця|д\.|ул\.|вул\.|Пров\.|Просп\.)?,?\s*(\d+[а-яА-Я]*)?$',
        text,
        re.IGNORECASE
    )

    if not match:
        # Якщо не вдалося розпарсити за стандартним форматом
        return text, ''

    # Витягуємо назву вулиці та номер будинку
    street = match.group(1).replace("вул., д.", '').replace("вул.,", '').replace(",", '').strip()
    house = match.group(2).strip() if match.group(2) else ''

    return street, house


def generate_title(data: dict, action: str) -> str:
    rooms = data.get('roomCount')
    area = data.get('areaTotal')
    floor = data.get('floor')
    floor_count = data.get('floorCount')

    action_str = 'Оренда' if action == 'rent' else 'Продаж'

    rooms_str = f'{rooms}-кімн.' if rooms else 'Студія'

    parts = [action_str, 'квартири', rooms_str]

    if area:
        parts.append(f'{area} м²')

    if floor and floor_count:
        parts.append(f'{floor}/{floor_count} пов.')

    return ' '.join(parts)


def all_parse_lun_offer(data: dict) -> dict:
    # Геодані
    city_id = None
    region_id = None
    city_name = None
    street = None
    house_number = None
    district = None
    residential_complex = None

    for geo in data.get('geoEntities', []):
        geo_type = geo.get('type')
        if geo_type == 'city':
            city_name = geo.get('name')
        elif geo_type == 'region':
            region_id = geo.get('geoId')
        elif geo_type == 'district':
            district = geo.get('name')
        elif geo_type == 'residential_complex':
            residential_complex = geo.get('name')
        elif geo_type == 'house':
            # Адреса береться з realtyGeoUrl або name
            geo_url = geo.get('realtyGeoUrl', {}) or {}
            link = geo_url.get('link', '')
            # Витягуємо вулицю і номер з link або name
            house_number = geo.get('name')

    # Вулиця з geoEntities або тексту
    street_geo = next(
        (g for g in data.get('geoEntities', []) if g.get('type') == 'residential_complex'),
        None
    )
    if street_geo:
        street = street_geo.get('address', '')
        street, house_number = parse_address(street)

    # Фото
    images = []
    for img in data.get('images', []):
        image_id = img.get('imageId')
        if image_id:
            images.append(f"https://market-images.lunstatic.net/lun-ua/840/1492/images/{image_id}.webp")

    main_photo = images[0] if images else None

    # Локація
    location = data.get('location')
    map_position = [f"{location[1]}", f"{location[0]}"] if location else None

    # Контакт
    contact = data.get('rieltorContact', {}) or {}
    is_realtor = contact.get('contactType') != 'owner'

    # Тип секції → action
    section_id = data.get('sectionId')
    action = 'rent' if section_id == 2 else 'sale'

    # Автор
    phones = contact.get('phones') or data.get('phones') or []
    phone = phones[0] if phones else None


    offer_data = {
        'name': contact.get('name'),
        'phone': f'+{phone}' if phone else None,
        'avatar': contact.get('avatar'),
        'ad_id': data.get('id'),
        'title': generate_title(data=data, action='Продаж' if action == 'sale' else 'Оренда'),
        'owner_type': 'business' if is_realtor else 'private',
        'source': 'LUNUA',
        'city_name': city_name,
        'price': data.get('price'),
        'base_price': data.get('price'),  # конвертація окремо
        'currency': (data.get('currency') or 'uah').upper(),

        'action': action,
        'is_realtor': is_realtor,
        'no_commission': data.get('withoutCommission', False),
        'city_id': city_id,
        'street': street if street and len(f"{street}") >= 4 else None,
        'house_number': house_number if street else None,
        'floors': data.get('floorCount'),
        'floor': data.get('floor'),
        'total_area': data.get('areaTotal'),
        'kitchen_area': data.get('areaKitchen'),
        'rooms': data.get('roomCount'),
        'updated_at': datetime.utcnow(),
        'map_position': map_position,
        'ad_link': f"https://lun.ua/realty/{data.get('id')}",
        'description': data.get('text'),
        'main_photo': main_photo,
        'photos': images,
        'refresh_time': datetime.utcnow(),
        'created_at': datetime.utcnow(),
        'irrelevance': 0,
        'residential_complex': residential_complex,
        'from_developer': False,
    }

    return offer_data

def parse_lun_offer(data: dict) -> dict:
    city_id = None
    region_id = None
    city_name = None
    street = None
    house_number = None
    district = None
    residential_complex = None

    for geo in data.get('geoEntities', []):
        geo_type = geo.get('type')
        if geo_type == 'city':
            city_id = geo.get('geoId')
            city_name = geo.get('name')
        elif geo_type == 'region':
            region_id = geo.get('geoId')
        elif geo_type == 'district':
            district = geo.get('name')
        elif geo_type == 'residential_complex':
            residential_complex = geo.get('name')
            # Вулиця з адреси ЖК
            address = geo.get('address', '')
            if address:
                street, house_number = parse_address(address)
        elif geo_type == 'house':
            house_number_raw = geo.get('name')
            # Вулицю беремо з link якщо немає ЖК
            geo_url = geo.get('realtyGeoUrl', {}) or {}
            link = geo_url.get('link', '')
            # link вигляд: /rent/kyiv/shota-rustaveli-st-27
            if link and not street:
                # Витягуємо slug вулиці без номера
                parts = link.rstrip('/').split('/')
                if parts:
                    slug = parts[-1]  # shota-rustaveli-st-27
                    # Відокремлюємо номер від назви вулиці
                    slug_parts = slug.rsplit('-', 1)
                    if len(slug_parts) == 2 and slug_parts[1].isdigit():
                        street = slug_parts[0].replace('-', ' ').title()
                        house_number = slug_parts[1]
                    else:
                        street = slug.replace('-', ' ').title()
                        house_number = house_number_raw

    # Фото
    images = []
    for img in data.get('images', []):
        image_id = img.get('imageId')
        if image_id:
            images.append(f"https://market-images.lunstatic.net/lun-ua/840/1492/images/{image_id}.webp")

    main_photo = images[0] if images else None

    # Локація
    location = data.get('location')
    map_position = [f"{location[1]}", f"{location[0]}"] if location else None

    # Контакт
    contact = data.get('rieltorContact', {}) or {}
    is_realtor = contact.get('contactType') != 'owner'

    # Action
    section_id = data.get('sectionId')
    action = 'rent' if section_id == 2 else 'sale'

    # Телефон
    phones = contact.get('phones') or data.get('phones') or []
    phone = phones[0] if phones else None

    offer_data = {
        'name': contact.get('name'),
        'phone': f'+{phone}' if phone else None,
        'avatar': contact.get('avatar'),
        'ad_id': data.get('id'),
        'title': generate_title(data=data, action='Продаж' if action == 'sale' else 'Оренда'),
        'owner_type': 'business' if is_realtor else 'private',
        'source': 'LUNUA',
        'city_name': city_name,
        'price': data.get('price'),
        'base_price': data.get('price'),
        'currency': (data.get('currency') or 'uah').upper(),
        'action': action,
        'is_realtor': is_realtor,
        'no_commission': data.get('withoutCommission', False),
        'city_id': city_id,
        'region_id': region_id,
        'street': street if street and len(f"{street}") >= 4 else None,
        'house_number': house_number if street else None,
        'floors': data.get('floorCount'),
        'floor': data.get('floor'),
        'total_area': data.get('areaTotal'),
        'kitchen_area': data.get('areaKitchen'),
        'rooms': data.get('roomCount'),
        'updated_at': datetime.utcnow(),
        'map_position': map_position,
        'ad_link': f"https://lun.ua/realty/{data.get('id')}",
        'description': data.get('text'),
        'main_photo': main_photo,
        'photos': images,
        'refresh_time': datetime.utcnow(),
        'created_at': datetime.utcnow(),
        'irrelevance': 0,
        'residential_complex': residential_complex,
        'from_developer': False,
    }

    return offer_data

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

def extract_full_info(url):
    try:
        response = requests.get(url, headers=config.headers, timeout=10)

        soup = BeautifulSoup(response.text, 'html.parser')
        scripts = soup.find_all('script')
        for script in scripts:
            if 'bankId' in script.text:
                data = extract_json_from_push(script.text)
                children = data.get('children')
                for c in children:
                    if type(c) == dict:
                        cards = c.get('realties', {}).get('cards')
                        for card in cards:
                                urlRaw = card.get('urlRaw')
                                offer_data = parse_lun_offer(card)
                                print(offer_data)


    except Exception as ex:
        print(ex)


if __name__ == '__main__':
    ads = extract_full_info(url='https://lun.ua/sale/kyiv/houses-irpin?without_broker=owner')
    print(ads)
