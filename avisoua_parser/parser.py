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
import models
from currency_api import currency_converter
from log import logger
from database import db_session
from datetime import datetime, timedelta
import base64

logger_parser = logging.getLogger('log.avisoua_parser.py')


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
    return dict_district.get(district)



def normalize_ua_phone(phone: str) -> str | None:
    import re
    if phone:
        digits = re.sub(r'\D', '', phone)
        if digits.startswith('380'):
            digits = '0' + digits[3:]
        return digits if len(digits) == 10 else ''
    return None


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


def parse_additional_info(soup):

    # Функція для безпечного парсингу числових значень
    def parse_numeric(text):
        if not text:
            return None
        # Витягуємо числа з тексту
        numbers = re.findall(r'\d+', str(text))
        return int(numbers[0]) if numbers else None

    # Функція для парсингу площі
    def parse_area(text):
        if not text:
            return None

        # Видаляємо м² та інші позначки
        text = text.replace('м²', '').replace(' ', '').replace('м2', '').strip()

        # Розбиваємо на частини
        areas = text.split('/')
        total_area = None
        kitchen_area = None

        def to_float(val):
            try:
                return float(val.replace(",", "."))
            except (ValueError, AttributeError):
                return None

        # Перетворюємо на float
        try:
            if len(areas) >= 0:
                total_area = to_float(areas[0])

            if len(areas) >= 2:
                kitchen_area = to_float(areas[2])

            return {
                'total_area': total_area,
                'kitchen_area': kitchen_area
            }
        except (ValueError, IndexError):
            return {}

    # Знаходимо всі додаткові інформаційні блоки
    info_items = soup.find_all('div', class_='additional-info__item')

    # Ініціалізуємо результат
    result = {
        'district': None,
        'rooms_count': None,
        'floor': None,
        'total_floors': None,
        'area': None
    }

    # Проходимо по кожному блоку
    for item in info_items:
        subtitle = item.find('h3', class_='additional-info__subtitle')
        text = item.find('p', class_='additional-info__text')

        if not subtitle or not text:
            continue

        subtitle_text = subtitle.get_text(strip=True)
        text_content = text.get_text(strip=True)

        # Район
        if subtitle_text == 'Район':
            result['district'] = text_content.replace('район', '').strip()

        # Кімнати
        elif subtitle_text == 'Кімнат':
            result['rooms_count'] = parse_numeric(text_content)

        # Поверх
        elif subtitle_text == 'Поверх':
            floor_parts = text_content.split(' з ')
            result['floor'] = parse_numeric(floor_parts[0])
            result['total_floors'] = parse_numeric(floor_parts[1]) if len(floor_parts) > 1 else None

        # Площа
        elif subtitle_text == 'Площа':
            result.update(parse_area(text_content))

    return result


async def extract_full_info(*, session, obj_url, ad_id):
    apartment_details = {'url': obj_url}
    try:

        async with session.get(url=obj_url, headers=headers) as response:
            text = await response.text()
            soup = BeautifulSoup(text, 'lxml')

            telephone = normalize_ua_phone(soup.find('span', class_='contacts__phone-text').text.strip())
            apartment_details['phone'] = telephone

            images = []
            image_script = soup.find_all('script', attrs={"type": "text/javascript"})

            if len(image_script) > 0:
                for im in image_script:
                    try:
                        if len(images) == 0:
                            if 'adImages' in im.text:
                                images_blocks = im.text.split("'")
                                for i in images_blocks:
                                    if '.jpg' in i and 'thumb' not in i:
                                        if i not in images:
                                            images.append(i)

                    except Exception as ex:
                        print(ex)

                apartment_details['images'] = images

            description = soup.find('p', class_='adt_descr-text').get_text(strip=True)
            apartment_details['description'] = description

            title_block = soup.find('h1', class_='adt__title').get_text(strip=True)

            map = soup.find('a', class_='js-open-map')
            if map:
                map_link = map.get('href')
                m = re.search(r'q=([0-9.]+)%2C([0-9.]+)', map_link)

                if m:
                    lat = float(m.group(1))
                    lon = float(m.group(2))
                    apartment_details['latitude'] = lat
                    apartment_details['longitude'] = lon

            address_block = soup.find('h2', class_='adt__address-text').get_text(strip=True)
            if address_block:
                street, house_number = parse_address(text=address_block)
                apartment_details['street'] = street
                apartment_details['house_number'] = house_number

            apartment_details['title'] = title_block

            owner_name = soup.find('p', class_='adt-details__title')
            apartment_details['owner_name'] = owner_name.get_text(strip=True) if owner_name else None

            apartment_details['profile_url'] = None

            apartment_details['is_realtor'] = 1 #if 'Риэлтор' in owner_type else 0
            # print(apartment_details)

            price_element = soup.find('p', class_='adt-details__price')
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

            params_table = soup.find('div', class_='additional-info__content')
            details = parse_additional_info(soup=params_table)
            apartment_details.update(details)

            return apartment_details
    except Exception as ex:
        logger_parser.warning(f'error during full_page_info - {ex} - {obj_url}')
        return apartment_details


def exist_contact(db, author_id, platform='AVISOUA'):
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

def create_contact(db, author_id, author_link, is_realtor, author_name, phone, platform='AVISOUA'):
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
            cards = soup.find_all('article', class_='card')
            current_ids = []
            for c in cards:
                try:
                    content = c.find('div', class_='card-content')
                    if content is None:
                        continue
                    ad_lk = "https://www.aviso.ua" + content.a.get('href')
                    ad_id = ad_lk.split('/')[-2]

                    current_ids.append(ad_id)
                except:
                    pass
            exists_db_ids = models.Offer.get_offers_created_at(ad_ids=current_ids, source='AVISOUA')

            for card in cards:
                content = card.find('div', class_='card-content')
                if content is None:
                    continue

                ad_link = "https://www.aviso.ua" + content.a.get('href')
                try:
                    ads_id = ad_link.split('/')[-2]

                    if int(ads_id) not in exists_db_ids:
                        ads_info = await extract_full_info(session=session, obj_url=ad_link, ad_id=ads_id)
                        base_price = ads_info.get('base_price')
                        offer_data = {
                            'ad_id': ads_id,
                            'title': content.a.text.strip(),
                            'owner_type': "business" if ads_info.get('is_realtor') else 'private',
                            'source': 'AVISOUA',
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
                            'street': ads_info.get('street', '') if len(ads_info.get('street', '')) < 4 else ads_info.get('street'),
                            'house_number': None if ads_info.get('street') is None else ads_info.get('house_number'),
                            'floors': ads_info.get('total_floors'),
                            'floor': ads_info.get('floor'),
                            'total_area': ads_info.get('total_area'),
                            'kitchen_area': ads_info.get('kitchen_area'),
                            'rooms': ads_info.get('rooms_count'),
                            'updated_at': datetime.now(),
                            'landmark': None,
                            'latitude': ads_info.get('latitude'),
                            'longitude': ads_info.get('longitude'),
                            'ad_link': ad_link,
                            'description': ads_info.get('description'),
                            'main_photo': ads_info.get('images', [None])[0],
                            'photos': ads_info.get('images'),
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
                            logger_parser.warning(f'Create new ads - {ads_id}')
                            if offer_data.get('action') == 'sale' and offer_data.get('city_id') in CITIES_FOR_DUPLICATES and offer_data.get(
                                    'type') in ['apartment', 'house']:
                                if CITIES_FOR_DUPLICATES.get(offer_data.get('city_id'), {}).get('detect_photo_duplicates'):
                                    await api_send_task({
                                        "ad_id": offer_data.get('ad_id'),
                                        "db_id": raw_offer.id,  # pk
                                        "action": offer_data.get('action'),
                                        "source": "AVISOUA",
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
                'url': 'https://www.aviso.ua/nerukhomist/prodazh-kvartyr-budynkiv/kvartyry/kyiv-misto/',
                'city_id': 10,
                'type': 'apartment',
                'action': 'sale',
            },
            {
                'url': 'https://www.aviso.ua/nerukhomist/prodazh-kvartyr-budynkiv/kimnaty/kyiv-misto/',
                'city_id': 10,
                'type': 'room',
                'action': 'sale',
            },

            {
                'url': 'https://www.aviso.ua/nerukhomist/prodazh-kvartyr-budynkiv/budynky/kyiv-misto/',
                'city_id': 10,
                'type': 'house',
                'action': 'sale',
            },

            {
                'url': 'https://www.aviso.ua/nerukhomist/orenda-kvartyr-budynkiv/kvartyry/kyiv-misto/',
                'city_id': 10,
                'type': 'apartment',
                'action': 'rent',
            },
            {
                'url': 'https://www.aviso.ua/nerukhomist/orenda-kvartyr-budynkiv/kimnaty/kyiv-misto/',
                'city_id': 10,
                'type': 'room',
                'action': 'rent',
            },
            {
                'url': 'https://www.aviso.ua/nerukhomist/orenda-kvartyr-budynkiv/budynky/kyiv-misto/',
                'city_id': 10,
                'type': 'house',
                'action': 'rent',
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
