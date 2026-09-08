import asyncio
import logging
import time
import re
import aiohttp
import requests
import json
from vector_service import api_send_task
import validate_addition_params
from bs4 import BeautifulSoup
from config import headers
import models
import ai_repair
from currency_api import currency_converter
from log import logger
from database import db_session
from datetime import datetime, timedelta
import re
from settings import settings

logger_parser = logging.getLogger('log.valion_parser.py')


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


async def parse_card(session: aiohttp.ClientSession, url: str) -> dict:
    async with session.get(url=url, headers=headers) as response:
        text = await response.text()

    soup = BeautifulSoup(text, 'html.parser')
    # --- ad_id ---
    ad_id = None
    id_label = soup.find(string=re.compile(r"ID об'єкта"))
    if id_label:
        val = id_label.find_parent().find_next_sibling()
        if val:
            ad_id = val.get_text(strip=True)

    # --- title / address ---
    title = None
    addr_el = soup.select_one('.object__dashboard-address')
    if addr_el:
        title = addr_el.get_text(strip=True)

    # --- description ---
    description = None
    desc_el = soup.select_one('.object__description-text')
    if desc_el:
        description = desc_el.get_text(separator='\n', strip=True)

    # --- price ---
    price = None
    price_el = soup.select_one('.object__dashboard-value .price-change')
    if price_el:
        price_str = price_el.get_text(strip=True).replace('\xa0', '').replace(' ', '')
        try:
            price = int(price_str)
        except ValueError:
            price = None

    # currency — always USD on this listing
    currency = 'USD'

    base_price = await currency_converter.convert_to_uah(price, currency or 'UAH')

    # --- location ---
    location_el = soup.select_one('.object__dashboard-location__text')
    location_text = location_el.get_text(strip=True) if location_el else ''
    # "Київ, Деснянський, Лісовий, м. Лісова"
    location_parts = [p.strip() for p in location_text.split(',')]
    city_name = location_parts[0] if location_parts else None

    # --- street & house_number from description ---
    street = None
    house_number = None
    street_match = re.search(r'вул\.\s*([\w\s\'\.]+),\s*(\d+[\w/]*)', description or '')
    if street_match:
        street = street_match.group(1).strip()
        house_number = street_match.group(2).strip()

    # --- characteristics ---
    chars = {}
    char_block = soup.select_one('.object__characteristics-inner')
    if char_block:
        labels = char_block.select('.object__characteristics-label')
        values = char_block.select('.object__characteristics-value')
        for lbl, val in zip(labels, values):
            key = lbl.get_text(strip=True).rstrip(':')
            chars[key] = val.get_text(strip=True)

    rooms_str = chars.get('Кімнат', '')
    rooms = int(rooms_str) if rooms_str.isdigit() else None

    total_area_str = re.sub(r'[^\d.]', '', chars.get('Загальна площа', ''))
    total_area = float(total_area_str) if total_area_str else None

    kitchen_area_str = re.sub(r'[^\d.]', '', chars.get('Площа кухні', ''))
    kitchen_area = float(kitchen_area_str) if kitchen_area_str else None


    floor_str = chars.get('Поверх', '')  # "2/9"
    floor, floors = None, None
    if '/' in floor_str:
        parts = floor_str.split('/')
        try:
            floor = int(parts[0])
            floors = int(parts[1])
        except ValueError:
            pass

    # --- agent / contact ---
    agent_name = None
    agent_name_el = soup.select_one('.agent__tile-name a')
    if agent_name_el:
        agent_name = agent_name_el.get_text(strip=True)

    phone = None
    phone_el = soup.select_one('.agent__tile-phone')
    if phone_el:
        raw = phone_el.get('data-raw', '') or phone_el.get('data-phone', '')
        phone = re.sub(r'[^\d+]', '', raw)

    avatar = None
    avatar_el = soup.select_one('.agent__tile-picture img')
    if avatar_el:
        avatar =  avatar_el.get('data-src')

    realtor_link = None
    realtor_link_el = soup.select_one('.agent__tile-picture a')
    if realtor_link_el:
        realtor_link = realtor_link_el.get('href')

    # --- photos ---
    photos = []
    main_photo = None
    seen = set()
    for slide in soup.select('.object__slider-top .swiper-slide a[data-fancybox]'):
        href = slide.get('href')
        if href and href not in seen:
            seen.add(href)
            photos.append(href)
    main_photo = photos[0] if photos else None


    # --- ad_link ---
    ad_link = f"https://valion.ua/uk/{ad_id}" if ad_id else None

    offer_data = {
        'name': agent_name,
        'phone': phone if phone else None,
        'avatar': avatar,
        'realtor_link': realtor_link,
        'city_name': city_name,
        'ad_id': ad_id,
        'title': title,
        'owner_type': 'business',
        'source': 'VALIONUA',
        'price': price,
        'base_price': base_price,
        'currency': currency.lower(),
        'action': 'sale',
        'is_realtor': True,
        'street': street if street and len(street) >= 4 else None,
        'house_number': house_number if street else None,
        'floors': floors,
        'floor': floor,
        'total_area': total_area,
        'kitchen_area': kitchen_area,
        'rooms': rooms,
        'updated_at': datetime.utcnow(),
        'ad_link': ad_link,
        'description': description,
        'main_photo': main_photo,
        'photos': photos,
        'refresh_time': datetime.utcnow(),
        'created_at': datetime.utcnow(),
        'residential_complex': None,
    }
    return offer_data






def exist_contact(db, author_id, platform='VALIONUA'):
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


def create_contact(db, author_id, author_link, is_realtor, author_name, phone, avatar=None, platform='VALIONUA'):
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
            avatar=avatar,

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
        async with session.get(url=obj_data.get('url'), headers=headers) as response:
            text = await response.text()

        soup = BeautifulSoup(text, 'html.parser')
        page_cards = soup.find_all('div', class_='object__tile object__tile--aflat')

        current_ids = [x.find('a', class_='address').get('href').split('/')[-2] for x in page_cards]

        ids = models.Offer.get_offers_created_at(ad_ids=current_ids, source='VALIONUA')

        for card in page_cards:
            try:
                ad_id = card.find('a', class_='address').get('href').split('/')[-2]

                if ad_id and int(ad_id) not in ids:

                    offer_data = await parse_card(session=session, url=card.find('a', class_='address').get('href'))
                    offer_data['type'] = obj_data.get('type')
                    offer_data['action'] = obj_data.get('action')
                    # print(offer_data)

                    offer_data['city_id'] = 10
                    offer_data['region_id'] = 10

                    if obj_data.get('action') == 'sale':
                        offer_data['repair'] = '1' if await ai_repair.has_repair(offer_data.get('description')) else None

                    with db_session() as db:

                        if offer_data.get('phone') is None:
                            offer_data['phone'] = '+380442001080' # Valion Rieltor

                        author_id = offer_data.get('phone').replace('+', '')[3:]

                        contact_id = exist_contact(
                            db=db,
                            author_id=author_id
                        )

                        if contact_id is False:
                            contact_id = create_contact(db=db,
                                                        author_id=author_id,
                                                        avatar=offer_data.get('avatar'),
                                                        author_link=offer_data.get('realtor_link'),
                                                        is_realtor=1,
                                                        phone=offer_data.get('phone'),
                                                        author_name=offer_data.get('name'))
                            offer_data['contact_id'] = contact_id
                        else:
                            offer_data['contact_id'] = contact_id

                        offer_data.pop('city_name')
                        offer_data.pop('avatar')
                        offer_data.pop('phone')
                        offer_data.pop('name')
                        offer_data.pop('realtor_link')
                        base_price = offer_data.pop('base_price')

                        if offer_data.get('type') == 'house':
                            offer_data['property_type_houses'] = validate_addition_params.detect_property_type_houses(text=offer_data.get('description'))

                        offer_data['no_commission'] = validate_addition_params.detect_no_commission(text=offer_data.get('description'))

                        raw_offer = models.Offer(**offer_data)
                        db.add(raw_offer)
                        db.commit()
                        db.refresh(raw_offer)
                        logger_parser.warning(f'Create new ads - {offer_data.get("ad_link")}')
                        if offer_data.get('action') == 'sale' and offer_data.get('city_id') == 10 and offer_data.get(
                                'type') in ['apartment', 'house'] and settings.TEST is False:
                            await api_send_task({
                                "ad_id": offer_data.get('ad_id'),
                                "db_id": raw_offer.id,  # pk
                                "action": offer_data.get('action'),
                                "source": "VALIONUA",
                                "type_obj": offer_data.get('type'),
                                "city_id": offer_data.get('city_id'),
                                "base_price": base_price,
                                "created_at": int(datetime.utcnow().timestamp())
                            })
                            logger_parser.info(
                                f'Send obj to vector service api - {offer_data.get("ad_id")}. db_id = {raw_offer.id}')

            except Exception as er:
                logger_parser.warning(f'during parser ex {er} - ads id: {obj_data}')

    except Exception as ex:
        logger_parser.warning(f'ПОМИЛКА ПАРСИНГУ - {ex}')


async def task_watch():
    print(f'start task {datetime.now()}')
    try:

        await currency_converter.update_exchange_rates()
        session = aiohttp.ClientSession()
        urls = [
            {
                'url': 'https://valion.ua/uk/navigation/prodazha-kvartir-v-kieve/?orderby=%D0%9F%D0%BE+%D0%BD%D0%BE%D0%B2%D0%B8%D0%B7%D0%BD%D0%B5',
                'region_id': 10,
                'city_id': 10,
                'type': 'apartment',
                'action': 'sale',
            },

        ]
        for obj_data in urls:
            await get_new_data(session=session,
                               obj_data=obj_data
                               )

        await session.close()
    except Exception as ex:
        logger_parser.warning(f'task_watch - {ex}')

    print(f'end task {datetime.now()}')


if __name__ == '__main__':
    asyncio.run(task_watch())
