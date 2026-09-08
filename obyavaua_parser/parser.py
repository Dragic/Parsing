import asyncio
import logging
import time
import re
import aiohttp
import requests
import json
from settings import settings
from bs4 import BeautifulSoup
from config import headers
import ai_repair
import models
from currency_api import currency_converter
from log import logger
from vector_service import api_send_task
import validate_addition_params
from database import db_session
from datetime import datetime, timedelta
import base64
import ai_agent
logger_parser = logging.getLogger('log.obyava_parser.py')

CITIES_FOR_DUPLICATES = models.City.get_region_city_settings(region_id=10) # Kiev


def district_pars(district):
    dict_district = {

        'Дніпровський': 15182,
        'Русановские сады': 15182,
        'Соцгород': 15182,
        'Березняки': 15182,
        "Соломенка": 15185,
        "Жуляны": 15185,
        "Батыева Гора": 15185,
        'Демиевка': 15184,

        "Отрадный": 15185,
        'Липки': 15189,
        'Позняки': 15181,
        'Осокорки': 15181,

        'Виноградарь':15188,
        'Борщаговка': 15186,
        'Татарка':15190,
        'Шевченківський':15190,

        'Троещина':15183,
        'Деснянський':15183,

        'Святошинський':15186,

        'Голосеево':15184,
        'Голосіївський':15184,
        'Голосеевский центр':15184,

        'Оболонь':15187,
        'Оболонський':15187,

        'Печерський':15189,
        'Ветряные Горы':15188,
        'Подільський':15188,
        'Бортничи':15181,
        'Дарницький':15181,

    }
    return dict_district.get(district)

def decode_phone(rebmun):
    try:
        return base64.b64decode(rebmun).decode("utf-8")
    except Exception as ex:
        logger_parser.warning(f'Error extract phone - {ex}')
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


def parse_details(soup):
    try:

        # Функція для безпечного перетворення тексту у float
        def safe_float(text):
            try:
                clear = text.replace('м2', '').strip()
                clear = float(clear.replace('соток', '').strip())
                return clear
            except (ValueError, AttributeError):
                return None

        # Функція для безпечного перетворення тексту у int
        def safe_int(text):
            try:
                return int(''.join(filter(str.isdigit, str(text))))
            except (ValueError, TypeError):
                return None

        # Площа
        total_area = soup.find('p', text=lambda t: 'Площа загальна, м2' in str(t) if t else False)
        total_area = safe_float(total_area.find_next('p').text) if total_area else None
        if total_area is None:
            total_area = soup.find('p', text=lambda t: 'Площа ділянки' in str(t) if t else False)
            total_area = safe_float(total_area.find_next('p').text) if total_area else None

        district_block = soup.find('p', text=lambda t: 'Район' in str(t) if t else False)
        district = district_block.find_next('p').text if district_block else None

        living_area = soup.find('p', text=lambda t: 'Площа житлова, м2' in str(t) if t else False)
        living_area = safe_float(living_area.find_next('p').text) if living_area else None

        kitchen_area = soup.find('p', text=lambda t: 'Кухня, м2' in str(t) if t else False)
        kitchen_area = safe_float(kitchen_area.find_next('p').text) if kitchen_area else None

        # Кількість кімнат
        rooms_count = soup.find('p', text=lambda t: 'Кількість кімнат' in str(t) if t else False)
        rooms_count = safe_int(rooms_count.find_next('p').text) if rooms_count else None

        # Поверх і поверховість
        floor = soup.find('p', text=lambda t: 'Поверх:' in str(t) if t else False)
        floor = safe_int(floor.find_next('p').text) if floor else None

        total_floors = soup.find('p', text=lambda t: 'В   -поверховому будинку:' in str(t) if t else False)
        total_floors = safe_int(total_floors.find_next('p').text) if total_floors else None

        return {
            'total_area': total_area,
            'living_area': living_area,
            'kitchen_area': kitchen_area,
            'rooms_count': rooms_count,
            'floor': floor,
            'total_floors': total_floors,
            'district': district
        }
    except Exception as ex:
        print(f'Eror params - {ex}')
        return {}


def get_user_data(ad_id):
    try:
        response = requests.get(f'https://obyava.ua/data/classified-page/{ad_id}?template=v2&lang=ua')
        return response.json()
    except Exception as ex:
        print(f'Eror user data - {ex}')
        return {}


async def extract_full_info(*, session, obj_url, ad_id):
    apartment_details = {'url': obj_url}
    try:

        async with session.get(url=obj_url, headers=headers) as response:
            text = await response.text()
            soup = BeautifulSoup(text, 'lxml')

            telephone = normalize_ua_phone(decode_phone(soup.find('span', class_='js-phone').get('data-rebmun')))

            apartment_details['phone'] = telephone

            images = []
            image_script = soup.find_all('div', class_='image-item')

            if len(image_script) > 0:
                for img in image_script:
                    img_link = img.get('data-image')
                    images.append(img_link)

                apartment_details['images'] = images

            description = soup.find('p', class_='offer-descr__text').get_text(strip=True)
            apartment_details['description'] = description

            title_block = soup.find('div', class_='offer__top-title').get_text(strip=True)

            apartment_details['title'] = title_block

            owner_data = get_user_data(ad_id=ad_id)
            if owner_data.get('user_data'):
                soup_owner = BeautifulSoup(owner_data.get('user_data'), 'html.parser')
                owner_name = soup_owner.find('p', class_='offer-descr__left-store-top-mid-title')
                apartment_details['owner_name'] = owner_name.get_text(strip=True) if owner_name else None

                profile_url = soup_owner.find('span', class_='js-profile-link')
                apartment_details['profile_url'] = profile_url.get('data-url') if profile_url else None

            apartment_details['is_realtor'] = 1 #if 'Риэлтор' in owner_type else 0
            # print(apartment_details)

            price_element = soup.find('p', class_='offer-right__mid-price-l')
            if price_element:
                if 'USD' in price_element.text:
                    currency = 'USD'
                elif 'EUR' in price_element.text:
                    currency = 'EUR'
                else:
                    currency = 'UAH'
                apartment_details['currency'] = currency
                price = int(re.search(r'\d+', price_element.text.replace(' ', '')).group())
                if price:
                    apartment_details['price'] = price
                    base_price = await currency_converter.convert_to_uah(price, currency or 'UAH')
                    apartment_details['base_price'] = base_price

            params_table = soup.find('div', class_='offer-descr__feature-top')
            details = parse_details(soup=params_table)
            apartment_details.update(details)

            return apartment_details
    except Exception as ex:
        logger_parser.warning(f'error during full_page_info - {ex} - {obj_url}')
        return apartment_details


def exist_contact(db, author_id, platform='OBYAVAUA'):
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


def create_contact(db, author_id, author_link, is_realtor, author_name, phone, platform='OBYAVAUA'):
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
            cards = soup.find_all('div', class_='single-item')
            current_ids = []
            for c in cards:
                try:
                    title_block = c.find('a', class_='single-item__title')
                    if title_block is None:
                        continue

                    ad_link = title_block.get('href')
                    ad_id = ad_link.split('-')[-1].replace('.html', '')

                    current_ids.append(ad_id)
                except:
                    pass
            exists_db_ids = models.Offer.get_offers_created_at(ad_ids=current_ids, source='OBYAVAUA')

            for card in cards:
                title_block = card.find('a', class_='single-item__title')
                if title_block is None:
                    continue

                ad_link = title_block.get('href')
                try:
                    ads_id = ad_link.split('-')[-1].replace('.html', '')

                    if int(ads_id) not in exists_db_ids:
                        ads_info = await extract_full_info(session=session, obj_url=ad_link, ad_id=ads_id)
                        base_price = ads_info.get('base_price')
                        offer_data = {
                            'ad_id': ads_id,
                            'title': title_block.text.strip(),
                            'owner_type': "business" if ads_info.get('is_realtor') else 'private',
                            'source': 'OBYAVAUA',
                            'price': ads_info.get('price'),
                            'currency': ads_info.get('currency', '').lower(),
                            'type': obj_data.get('type'),
                            'action': obj_data.get('action'),
                            'is_realtor': ads_info.get('is_realtor'),
                            'no_commission': False,
                            'market_type': None,
                            'residential_complex': ads_info.get('residential_complex'),
                            'city_id': obj_data.get('city_id'),
                            'district_id': district_pars(ads_info.get('district')),
                            'region_id': 10,
                            'street': ads_info.get('street'),
                            'house_number': ads_info.get('house_number'),
                            'floors': ads_info.get('total_floors'),
                            'floor': ads_info.get('floor'),
                            'total_area': ads_info.get('total_area') if obj_data.get('type') == 'land' else ads_info.get('total_area'),
                            'kitchen_area': ads_info.get('kitchen_area'),
                            'rooms': ads_info.get('rooms_count'),
                            'updated_at': datetime.now(),
                            'landmark': None,
                            'ad_link': ad_link,
                            'description': ads_info.get('description'),
                            'main_photo': ads_info.get('images', [None])[0],
                            'photos': ads_info.get('images'),
                            'e_oselya': None,
                            'refresh_time': datetime.now(),
                            'created_at': datetime.now(),

                        }

                        if offer_data.get('type') == 'house':
                            offer_data['property_type_houses'] = validate_addition_params.detect_property_type_houses(
                                text=offer_data.get('description'))

                        offer_data['no_commission'] = validate_addition_params.detect_no_commission(
                            text=offer_data.get('description'))

                        if offer_data.get('action') == 'sale':
                            offer_data['repair'] = '1' if await ai_repair.has_repair(
                                offer_data.get('description')) else None

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
                            logger_parser.info(f'Create new ads - {ads_id}')
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
                                        "source": "OBYAVAUA",
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
                'url': 'https://obyava.ua/ua/nedvizhimost/prodazha-kvartir/kiev?currency=usd',
                'city_id': 10,
                'type': 'apartment',
                'action': 'sale',
            },
            {
                'url': 'https://obyava.ua/ua/nedvizhimost/arenda-kvartir/kiev',
                'city_id': 10,
                'type': 'apartment',
                'action': 'rent',
            },

            {
                'url': 'https://obyava.ua/ua/nedvizhimost/prodazha-domov/kiev?currency=usd',
                'city_id': 10,
                'type': 'house',
                'action': 'sale',
            },
            {
                'url': 'https://obyava.ua/ua/nedvizhimost/arenda-domov/kiev',
                'city_id': 10,
                'type': 'house',
                'action': 'rent',
            },

            {
                'url': 'https://obyava.ua/ua/nedvizhimost/prodazha-zemli/kiev?currency=usd',
                'city_id': 10,
                'type': 'land',
                'action': 'sale',
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
