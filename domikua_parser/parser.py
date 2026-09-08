import asyncio
import logging
import time
import re
import aiohttp
import requests
import json
from vector_service import api_send_task
from bs4 import BeautifulSoup
from config import headers
import ai_repair
import models
import validate_addition_params
from sqlalchemy import null
from currency_api import currency_converter
from log import logger
from database import db_session
from datetime import datetime, timedelta

logger_parser = logging.getLogger('log.domikua_parser.py')

CITIES_FOR_DUPLICATES = models.City.get_region_city_settings(region_id=10) # Kiev


def normalize_ua_phone(phone: str) -> str | None:
    import re
    if phone:
        digits = re.sub(r'\D', '', phone)
        if digits.startswith('380'):
            digits = '0' + digits[3:]
        return digits if len(digits) == 10 else ''
    return None


def parse_address(text: str):
    text = text.strip()
    parts = [p.strip() for p in text.split(',') if p.strip()]

    if not parts:
        return '', ''

    # city = parts[0] if len(parts) > 0 else ''
    street = parts[1] if len(parts) > 1 else ''
    house = ''.join(parts[2:]) if len(parts) > 2 else ''

    # Прибираємо типи вулиці
    import re
    street = re.sub(
        r'\b(ул\.?|вул\.?|улица|шоссе|просп\.?|проспект|бульвар)\b\.?',
        '',
        street,
        flags=re.IGNORECASE
    ).strip()

    return street, house


async def extract_full_info(*, session, obj_url):
    apartment_details = {'url': obj_url}
    try:

        async with session.get(url=obj_url, headers=headers) as response:
            text = await response.text()
            soup = BeautifulSoup(text, 'lxml')
            encode_script = {}

            scripts = soup.find_all('script', attrs={'type': 'application/ld+json'})
            for scr in scripts:
                if 'telephone' in scr.text and not encode_script:
                    encode_script = json.loads(scr.text)

            images = []
            image_script = encode_script.get('image', [])
            if len(image_script) > 0:
                for img in image_script:
                    img_id = img.split('/')[-1]
                    images.append(f'https://domik.ua/images/orig/full/{img_id}')

                apartment_details['images'] = images

            telephone = normalize_ua_phone(encode_script.get('telephone'))
            apartment_details['phone'] = telephone

            apartment_details['profile_url'] = f'https://domik.ua/profile/all-objects-search?customPhones={telephone}'

            geo = encode_script.get('geo', {})
            latitude = geo.get('latitude')
            longitude = geo.get('longitude')
            if latitude and longitude:
                apartment_details['latitude'] = latitude
                apartment_details['longitude'] = longitude

            description = soup.find('div', class_='pageObject__text_description').get_text(strip=True)
            apartment_details['description'] = description

            address_block = soup.find('div', class_='pageObject__blockMap')
            if address_block:
                span_text_address = address_block.find('span', class_='pageObject__text pageObject__text_info').get_text(strip=True)
                street, house_number = parse_address(text=span_text_address)
                apartment_details['street'] = street
                apartment_details['house_number'] = house_number

            title = soup.find('div', class_='pageObject__title').get_text(strip=True)
            apartment_details['title'] = title

            owner_name = soup.find('span', class_='pageObject__text_ownerName').get_text(strip=True)
            apartment_details['owner_name'] = owner_name

            owner_type = soup.find('span', class_='pageObject__text_ownerPost').get_text(strip=True)
            apartment_details['is_realtor'] = 1 if 'Риэлтор' in owner_type else 0

            price_element = soup.find('span', class_='pageObject__text_priceMain')
            if price_element:
                price_text = price_element.get_text(strip=True)
                apartment_details['currency'] = 'UAH'
                # Витягуємо валюту та число
                currency_match = re.search(r'([$€])', price_text)
                price_match = re.search(r'(\d+\s*\d*)', price_text.replace(' ', ''))

                if currency_match:
                    if '€' in currency_match.group(1):
                        currency = 'EUR'
                    elif '$' in currency_match.group(1):
                        currency = 'USD'
                    else:
                        currency = 'UAH'
                    apartment_details['currency'] = currency

                if price_match:
                    price = int(price_match.group(1).replace(' ', ''))
                    apartment_details['price'] = price
                    if price:
                        base_price = await currency_converter.convert_to_uah(price, currency or 'UAH')
                        apartment_details['base_price'] = base_price

            params_table = soup.find_all('tr', class_='pageObject__tableTr')
            for row in params_table:
                try:
                    label = row.find('span', class_='pageObject__text_label')
                    value = row.find('span', class_='pageObject__text_info')

                    if label and value:
                        label_text = label.get_text(strip=True)
                        value_text = value.get_text(strip=True)

                        # Обробка типу квартири
                        if label_text == 'Тип':
                            # Витягуємо число з назви квартири
                            match = re.search(r'(\d+)', value_text)
                            if match:
                                apartment_details['rooms_count'] = int(match.group(1))

                        # Спеціальна обробка для площі
                        elif 'площадь' in label_text.lower() or 'площадь участка' in label_text.lower():
                            # Витягуємо тільки числове значення
                            match = re.search(r'(\d+\.?\d*)', value_text)
                            if match:
                                apartment_details[label_text] = float(match.group(1))
                        else:
                            apartment_details[label_text] = value_text
                except Exception as ex:
                    print(f'Error pars - {ex}')
            return apartment_details
    except Exception as ex:
        logger_parser.warning(f'error during full_page_info - {ex} - {obj_url}')
        return apartment_details

def exist_contact(db, author_id, platform='DOMIKUA'):
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

def create_contact(db, author_id, author_link, is_realtor, author_name, phone, platform='DOMIKUA'):
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
            cards = soup.find_all('div', class_='viewTile viewTile_domik viewTile_list viewTile_object')
            current_ids = []
            for c in cards:
                try:
                    link = c.find('a', class_='viewTile__link_fill').get('href')
                    ad_id = link.split('-id')[-1].replace('.html', '')
                    current_ids.append(ad_id)
                except:
                    pass
            exists_db_ids = models.Offer.get_offers_created_at(ad_ids=current_ids, source='DOMIKUA')

            for card in cards:
                try:

                    link = card.find('a', class_='viewTile__link_fill').get('href')
                    ads_id = link.split('-id')[-1].replace('.html', '')

                    ad_link = 'https://domik.ua' + link

                    if int(ads_id) not in exists_db_ids:
                        ads_info = await extract_full_info(session=session, obj_url=ad_link)
                        floors = ads_info.get('Этажей в доме') if ads_info.get('Этажей в доме', '').isdigit() else None
                        floor = ads_info.get('Этаж') if ads_info.get('Этаж', '').isdigit() else None
                        base_price = ads_info.get('base_price')
                        offer_data = {
                            'ad_id': ads_id,
                            'title': ads_info.get('title'),
                            'owner_type': "business" if ads_info.get('is_realtor') else 'private',
                            'source': 'DOMIKUA',
                            'price': ads_info.get('price'),
                            'currency': ads_info.get('currency').lower(),
                            'type': obj_data.get('type'),
                            'action': obj_data.get('action'),
                            'is_realtor': ads_info.get('is_realtor'),
                            'no_commission': False,
                            'market_type': None,
                            'residential_complex': None,
                            'city_id': obj_data.get('city_id'),
                            'district_id': None,
                            'region_id': 10,
                            'street': None if len(ads_info.get('street', '')) < 4 else ads_info.get('street'),
                            'house_number': None if ads_info.get('street') is None else ads_info.get('house_number'),
                            'floors': floors,
                            'floor': floor,
                            'total_area': ads_info.get('Площадь участка') if obj_data.get('type') == 'land' else ads_info.get('Общая площадь'),
                            'kitchen_area': ads_info.get('Площадь кухни'),
                            'rooms': ads_info.get('rooms_count'),
                            'updated_at': datetime.now(),
                            'latitude': ads_info.get('latitude'),
                            'longitude': ads_info.get('longitude'),
                            'landmark': None,
                            'ad_link': ad_link,
                            'description': ads_info.get('description'),
                            'main_photo': ads_info.get('images', [None])[0],
                            'photos': ads_info.get('images'),

                            'e_oselya': None,
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
                            contact_id = exist_contact(
                                    db=db,
                                    author_id=phone_id
                                )

                            if contact_id is False:
                                contact_id = create_contact(db=db,
                                                            author_link=author_link,
                                                            author_id=phone_id,
                                                            is_realtor=1 if ads_info.get('is_realtor') else 0,
                                                            phone=f'+38{phone_id}',
                                                            author_name=author_name)
                                offer_data['contact_id'] = contact_id
                            else:
                                offer_data['contact_id'] = contact_id

                            raw_offer = models.Offer(**offer_data)
                            db.add(raw_offer)
                            db.commit()
                            logger_parser.info(f'Create new ads - {link}')
                            db.refresh(raw_offer)
                            if offer_data.get('action') == 'sale' and offer_data.get(
                                    'city_id') in CITIES_FOR_DUPLICATES and offer_data.get(
                                    'type') in ['apartment', 'house']:
                                if CITIES_FOR_DUPLICATES.get(offer_data.get('city_id'), {}).get(
                                        'detect_photo_duplicates'):
                                    await api_send_task({
                                        "ad_id": offer_data.get('ad_id'),
                                        "db_id": raw_offer.id,  # pk
                                        "action": offer_data.get('action'),
                                        "source": "DOMIKUA",
                                        "type_obj": offer_data.get('type'),
                                        "city_id": offer_data.get('city_id'),
                                        "base_price": base_price,
                                        "created_at": int(datetime.now().timestamp())
                                    })
                                    logger_parser.info(
                                        f'Send obj to vector service api - {offer_data.get("ad_id")}. db_id = {raw_offer.id}')

                except Exception as er:
                    logger_parser.warning(f'during parser ex {er} - ads id: {obj_data}')
    except Exception as ex:
        logger_parser.warning(f'ПОМИЛКА ПАРСИНГУ {ex}')


async def task_watch():
    print(f'start task {datetime.now()}')
    try:
        await currency_converter.update_exchange_rates()
        session = aiohttp.ClientSession()
        urls = [
            {
                'url': 'https://domik.ua/kupit-kvartiru-kiev?order=1',
                'city_id': 10,
                'type': 'apartment',
                'action': 'sale',
            },
            {
                'url': 'https://domik.ua/kupit-dom-kiev?order=1',
                'city_id': 10,
                'type': 'house',
                'action': 'sale',
            },
            {
                'url': 'https://domik.ua/kupit-ofis-kiev?order=1',
                'city_id': 10,
                'type': 'commercial',
                'action': 'sale',
            },
            {
                'url': 'https://domik.ua/kupit-uchastok-kiev?order=1',
                'city_id': 10,
                'type': 'land',
                'action': 'sale',
            },

            {
                'url': 'https://domik.ua/snyat-kvartiru-kiev?order=1',
                'city_id': 10,
                'type': 'apartment',
                'action': 'rent',
            },

            {
                'url': 'https://domik.ua/snyat-dom-kiev?order=1',
                'city_id': 10,
                'type': 'house',
                'action': 'rent',
            },
            {
                'url': 'https://domik.ua/snyat-ofis-kiev?order=1',
                'city_id': 10,
                'type': 'commercial',
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
