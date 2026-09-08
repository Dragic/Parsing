import asyncio
import logging
import time
import re
import aiohttp
import requests
import json
import ai_repair
from vector_service import api_send_task
import validate_addition_params
from bs4 import BeautifulSoup
from config import headers
from settings import settings
import models
from currency_api import currency_converter
from log import logger
from database import db_session
from datetime import datetime, timedelta
import base64

logger_parser = logging.getLogger('log.M2BOMBER_parser.py')

CITIES_FOR_DUPLICATES = models.City.get_region_city_settings(region_id=10) # Kiev


def district_pars(district):
    dict_district = {
        'Шевченківський':15190,
        'Дніпровський':15182,
        'Деснянський':15183,
        'Святошинський':15186,
        'Голосіївський':15184,
        "Солом'янський":15185,
        'Оболонський':15187,
        'Печерський':15189,
        'Подільський':15188,
        'Дарницький':15181,
    }
    for k, v in dict_district.items():
        if k in district:
            return v
    return None



def normalize_ua_phone(phone: str) -> str | None:
    import re
    if phone:
        digits = re.sub(r'\D', '', phone)
        if digits.startswith('380'):
            digits = '0' + digits[3:]
        return digits if len(digits) == 10 else ''
    return None


def parse_address(text: str):
    # Попередня обробка тексту
    text = text.strip()

    # Ініціалізація змінних
    street = None
    house = None
    district = None

    # Розбираємо різні варіанти адрес
    # Приклад: "вулиця Івана Виговського, район Подільський, Київ, вул. Івана Виговського 10Е"
    parts = [p.strip() for p in text.split(',')]

    # Пошук номера будинку
    for part in parts:
        # Пошук номера будинку з літерами
        house_match = re.search(r'\b(\d+[а-яА-Я]*)\b', part)
        if house_match:
            house = house_match.group(1)

    # Пошук вулиці
    for part in parts:
        # Видаляємо службові слова
        street_match = re.sub(
            r'\b(вул\.|ул\.|вулиця|улица|просп\.|проспект|д\.|дом|метро|мікрорайон|район)\b',
            '',
            part,
            flags=re.IGNORECASE
        ).strip()

        # Якщо залишився текст і немає номера будинку
        if street_match and not re.search(r'\d', street_match):
            street = street_match

    # Пошук району
    for part in parts:
        if 'район' in part.lower():
            district_match = re.search(r'район\s+(.+)', part, re.IGNORECASE)
            if district_match:
                district = district_match.group(1).strip()

    return street, house, district

def parse_apartment_details(soup):
    total_area = None
    rooms_count = None
    floor = None
    total_floors = None
    try:
        soup = soup.find('ul', class_='fullcard-tags')
        # Функція для безпечного перетворення тексту у float
        def safe_float(text):
            try:
                # Видаляємо 'м²' та замінюємо кому на крапку
                cleaned_text = text.replace('м²', '').replace(',', '.').strip()
                return float(cleaned_text)
            except (ValueError, AttributeError):
                return None

        # Функція для безпечного перетворення тексту у int
        def safe_int(text):
            try:
                # Витягуємо число з тексту
                return int(''.join(filter(str.isdigit, str(text))))
            except (ValueError, TypeError):
                return None

        # Знаходимо всі теги <li>
        tags = soup.find_all('li')

        # Ініціалізуємо змінні
        total_area = None
        rooms_count = None
        floor = None
        total_floors = None

        # Перебираємо теги для пошуку інформації
        for tag in tags:
            try:
                text = tag.get_text(strip=True)

                # Пошук площі
                if 'м²' in text:
                    total_area = safe_float(text)

                # Пошук кількості кімнат
                if '-кімн' in text:
                    rooms_count = safe_int(text)

                # Пошук поверху
                if 'поверх' in text:
                    floor_match = re.search(r'поверх\s*(\d+)\s*/\s*(\d+)', text)
                    if floor_match:
                        floor = safe_int(floor_match.group(1))
                        total_floors = safe_int(floor_match.group(2))
            except Exception as ex:
                print(f'Eror inside - {ex}')
    except Exception as ex:
        print(f'Eror global inside - {ex}')

    return {
        'total_area': total_area,
        'rooms_count': rooms_count,
        'floor': floor,
        'total_floors': total_floors
    }


def extract_phone(ad_id):
    try:
        proxy = {
            'http': settings.PROXY,
            'https': settings.PROXY,
        }
        response = requests.get(f'https://ua.m2bomber.com/obj/{ad_id}/phones',
                                proxies=proxy,
                                headers=headers,
                                timeout=15)
        if len(response.text) > 26:
            return response.text.split('</h4>')[0]
        return response.text
    except:
        return ''

async def extract_full_info(*, session, obj_url):
    apartment_details = {'url': obj_url}
    try:

        async with session.get(url=obj_url, headers=headers) as response:
            text = await response.text()
            soup = BeautifulSoup(text, 'lxml')
            ad_id_block = soup.find('ul', class_='fullcard-meta')
            if ad_id_block:
                ad_id = ad_id_block.find_all('li')[0].text.replace("Об'єкт UA-", '').strip()
                apartment_details['ad_id'] = ad_id

                telephone = extract_phone(ad_id)
                apartment_details['phone'] = normalize_ua_phone(telephone.replace("</h4>", '').replace("<h4>", ''))

            images = []
            image_script = soup.find_all('a', attrs={"data-fancybox": "gallery"})

            if len(image_script) > 0:
                for im in image_script:
                    try:
                        images.append('https://ua.m2bomber.com' + im.get('href'))

                    except Exception as ex:
                        print(ex)

                apartment_details['images'] = images

            description = soup.find('div', class_='fullcard-desc').get_text(strip=True)
            apartment_details['description'] = description

            title_block = soup.find('h1').get_text(strip=True)

            map = soup.find('div', attrs={"id": 'map'})
            if map:
                lon = map.get('data-map-lon')
                lat = map.get('data-map-lat')
                apartment_details['latitude'] = lat
                apartment_details['longitude'] = lon

            address_block = soup.find('div', class_='breadcrumbs')
            if address_block:
                address = [x.text.strip() for x in address_block.find_all('li')]
                if len(address) > 3:
                    split_address = ', '.join(address[3:])
                    street, house_number, district = parse_address(split_address)
                    apartment_details['street'] = None if street in ['міст'] else street
                    apartment_details['house_number'] = house_number if apartment_details.get('street') else None
                apartment_details['district'] = ', '.join(address)

            apartment_details['title'] = title_block

            owner_name = soup.find('div', class_='fullcard-author')
            if owner_name:
                if 'агент' in owner_name.get_text(strip=True):
                    apartment_details['owner_name'] = 'Агентство'
                    apartment_details['is_realtor'] = 1
                else:
                    apartment_details['owner_name'] = 'Власник'
                    apartment_details['is_realtor'] = 0

                profile_link = owner_name.find('a', class_='arrow-link')
                apartment_details['profile_url'] = "https://ua.m2bomber.com" + profile_link.get('href') if profile_link\
                    else None

            price_element = soup.find('span', attrs={"id": "fullPriceValueHolder"})
            if price_element:
                if '$' in price_element.text:
                    currency = 'USD'
                elif '€' in price_element.text:
                    currency = 'EUR'
                else:
                    currency = 'UAH'
                apartment_details['currency'] = currency
                price = int(re.search(r'\d+', price_element.text.replace(' ', '')).group())
                if price:
                    apartment_details['price'] = price
                    base_price = await currency_converter.convert_to_uah(price, currency or 'UAH')
                    apartment_details['base_price'] = base_price

            details = parse_apartment_details(soup=soup)
            apartment_details.update(details)

            return apartment_details
    except Exception as ex:
        logger_parser.warning(f'error during full_page_info - {ex} - {obj_url}')
        return apartment_details


def exist_contact(db, author_id, platform='M2BOMBER'):
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


def create_contact(db, author_id, author_link, is_realtor, author_name, phone, platform='M2BOMBER'):
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
            async with session.get(url=obj_data.get('url'), headers=headers) as response:
                text = await response.text()

            soup = BeautifulSoup(text, 'lxml')
            cards = soup.find_all('a', class_='item-card-long-title')
            current_ids = []
            for c in cards:
                try:
                    ad_id = c.get('href').split('obj/')[-1].split('/')[0]

                    current_ids.append(ad_id)
                except:
                    pass
            exists_db_ids = models.Offer.get_offers_created_at(ad_ids=current_ids, source='M2BOMBER')

            for card in cards:

                ad_link = "https://ua.m2bomber.com" + card.get('href')
                ad_id = card.get('href').split('obj/')[-1].split('/')[0]
                try:
                    # print(f'GET: {ad_link}')

                    if int(ad_id) not in exists_db_ids:
                        ads_info = await extract_full_info(session=session, obj_url=ad_link)
                        if ads_info.get('currency') is None:
                            continue

                        base_price = ads_info.get('base_price')
                        offer_data = {
                            'ad_id': ad_id,
                            'title': ads_info.get('title'),
                            'owner_type': "business" if ads_info.get('is_realtor') else 'private',
                            'source': 'M2BOMBER',
                            'price': ads_info.get('price'),
                            'currency': ads_info.get('currency').lower(),
                            'type': obj_data.get('type'),
                            'action': obj_data.get('action'),
                            'is_realtor': ads_info.get('is_realtor'),
                            'no_commission': False,
                            'market_type': None,
                            'residential_complex': None,
                            'city_id': obj_data.get('city_id'),
                            'district_id': district_pars(ads_info.get('district')),
                            'region_id': 10,
                            'street': ads_info.get('street', '') if ads_info.get('street', []) else ads_info.get('street'),
                            'house_number': None if ads_info.get('street') is None else ads_info.get('house_number'),
                            'floors': ads_info.get('total_floors'),
                            'floor': ads_info.get('floor'),
                            'total_area': ads_info.get('total_area'),
                            'kitchen_area': ads_info.get('kitchen_area'),
                            'rooms': ads_info.get('rooms_count'),
                            'updated_at': datetime.now(),

                            'latitude': ads_info.get('latitude'),
                            'longitude': ads_info.get('longitude'),

                            'ad_link': ad_link,
                            'description': ads_info.get('description'),
                            'main_photo': ads_info.get('images', [None])[0],
                            'photos': ads_info.get('images', []),

                            'refresh_time': datetime.now(),
                            'created_at': datetime.now(),
                        }

                        if offer_data.get('action') == 'sale':
                            offer_data['repair'] = '1' if await ai_repair.has_repair(
                                offer_data.get('description')) else None

                        if offer_data.get('type') == 'house':
                            offer_data['property_type_houses'] = validate_addition_params.detect_property_type_houses(
                                text=offer_data.get('description'))

                        offer_data['no_commission'] = validate_addition_params.detect_no_commission(
                            text=offer_data.get('description'))

                        phone_id = ads_info.get('phone')
                        author_link = ads_info.get('profile_url')
                        author_name = ads_info.get('owner_name')
                        with db_session() as db:

                            # Отримуємо або створюємо контакт
                            contact_id = exist_contact(
                                    db=db,
                                    author_id=phone_id
                                )

                            if contact_id is False:
                                contact_id = create_contact(db=db,
                                                            author_id=phone_id,
                                                            author_link=author_link,
                                                            is_realtor=1 if ads_info.get('is_realtor') else 0,
                                                            phone=f'+38{phone_id}',
                                                            author_name=author_name)
                                offer_data['contact_id'] = contact_id
                            else:
                                offer_data['contact_id'] = contact_id

                            raw_offer = models.Offer(**offer_data)
                            db.add(raw_offer)
                            db.commit()
                            db.refresh(raw_offer)
                            logger_parser.warning(f'Create new ads - {ad_link}')
                            if offer_data.get('action') == 'sale' and offer_data.get(
                                    'city_id') in CITIES_FOR_DUPLICATES and offer_data.get(
                                    'type') in ['apartment', 'house']:
                                if CITIES_FOR_DUPLICATES.get(offer_data.get('city_id'), {}).get(
                                        'detect_photo_duplicates'):
                                    await api_send_task({
                                        "ad_id": offer_data.get('ad_id'),
                                        "db_id": raw_offer.id,  # pk
                                        "action": offer_data.get('action'),
                                        "source": "M2BOMBER",
                                        "type_obj": offer_data.get('type'),
                                        "city_id": offer_data.get('city_id'),
                                        "base_price": base_price,
                                        "created_at": int(datetime.now().timestamp())
                                    })
                                    logger_parser.info(
                                        f'Send obj to vector service api - {offer_data.get("ad_id")}. db_id = {raw_offer.id}')

                except Exception as er:
                    logger_parser.warning(f'during parser ex {er} - ads id: {obj_data}.Link: {ad_link}')
    except Exception as ex:
        logger_parser.warning(f'ПОМИЛКА ПАРСИНГУ {ex}')


async def task_watch():
    print(f'start task {datetime.now()}')
    try:
        await currency_converter.update_exchange_rates()
        session = aiohttp.ClientSession()
        urls = [
            {
                'url': 'https://ua.m2bomber.com/flat-sell/kiiv-11-421866',
                'city_id': 10,
                'type': 'apartment',
                'action': 'sale',
            },
            {
                'url': 'https://ua.m2bomber.com/commercial-sell/kiiv-11-421866',
                'city_id': 10,
                'type': 'commercial',
                'action': 'sale',
            },

            {
                'url': 'https://ua.m2bomber.com/house-sell/kiiv-11-421866',
                'city_id': 10,
                'type': 'house',
                'action': 'sale',
            },
            {
                'url': 'https://ua.m2bomber.com/flat-rent/kiiv-11-421866',
                'city_id': 10,
                'type': 'apartment',
                'action': 'rent',
            },
            {
                'url': 'https://ua.m2bomber.com/house-rent/kiiv-11-421866',
                'city_id': 10,
                'type': 'house',
                'action': 'rent',
            }
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
