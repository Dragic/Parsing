import asyncio
import logging
import time
import re
import aiohttp
import requests
import json
from vector_service import api_send_task
from sqlalchemy import null
from bs4 import BeautifulSoup
from config import headers
import ai_repair
import validate_addition_params
from settings import settings
import models
from currency_api import currency_converter
from log import logger
from database import db_session
from datetime import datetime, timedelta
import base64

logger_parser = logging.getLogger('log.ESTUA_parser.py')


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


def get_page_link(url):
    try:
        response = requests.get(url=url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        obj_url = soup.find('meta', attrs={"http-equiv": "refresh"}).get('content')
        return obj_url.replace('3;url=', '')
    except Exception as ex:
        logger_parser.warning(f'Error page link - {ex}')
        return None

def parse_address(text: str):
    # Ініціалізація змінних
    street = None
    house = None
    try:
        parts = [p.strip() for p in text.split(',')]

        # Беремо перший та другий елементи
        street = parts[0].replace('вул.', '').replace('просп.', '').replace('наб.', '').replace('спуск', 'спуск ').strip()
        house = parts[1] if len(parts) > 1 else None

        return street, house

    except Exception as ex:
        logger_parser.warning(f'Error pars address - {ex}. Input: {text}')

    return street, house


def parse_apartment_details(html_content):
        soup = html_content.find('div', class_='sidebar__section sidebar__section--maininfo')
        # Словники для пошуку назв полів
        labels = {
            'rooms': ['Количество комнат', 'Кількість кімнат'],
            'floor': ['Этаж', 'Поверх'],
            'total_floors': ['Этажность', 'Кількість поверхів'],
            'total_area': ['Общая площадь', 'Загальна площа'],
            'kitchen_area': ['Площадь кухни', 'Площа кухні']
        }

        # Функція для безпечного перетворення тексту у float
        def safe_float(text):
            try:
                # Видаляємо 'м²' та замінюємо пробіли
                cleaned_text = text.replace('м²', '').replace('&nbsp;', '').replace(' ', '').replace(',', '.').strip()
                return float(cleaned_text)
            except (ValueError, AttributeError):
                return None

        # Функція для безпечного перетворення тексту у int
        def safe_int(text):
            try:
                # Видаляємо пробіли та &nbsp;
                cleaned_text = text.replace('&nbsp;', '').replace(' ', '').replace(' ', '').strip()
                return int(cleaned_text)
            except (ValueError, TypeError):
                print('errr price', text)
                return None

        # Парсинг ціни та валюти
        price_block = soup.find('span', class_='active est-dropdown-toggle currency')
        price = None
        currency = None
        if price_block:
            price = safe_int(price_block.get('data-price-total', ''))
            currency = price_block.get('data-currency')

        # Парсинг параметрів з таблиці
        info_table = soup.find('table', class_='info-table')
        result = {
            'price': price,
            'currency': currency.lower() if currency else None,
            'rooms_count': None,
            'floor': None,
            'total_floors': None,
            'total_area': None,
            'kitchen_area': None
        }

        if info_table:
            rows = info_table.find_all('tr')
            for row in rows:
                th = row.find('th')
                td = row.find('td')
                if th and td:
                    label_text = th.get_text(strip=True)
                    value = td.get_text(strip=True)

                    # Перевірка назв для кількості кімнат
                    if any(label in label_text for label in labels['rooms']):
                        result['rooms_count'] = safe_int(value)

                    # Перевірка назв для поверху
                    elif any(label in label_text for label in labels['floor']):
                        result['floor'] = safe_int(value)

                    # Перевірка назв для поверховості
                    elif any(label in label_text for label in labels['total_floors']):
                        result['total_floors'] = safe_int(value)

                    # Перевірка назв для загальної площі
                    elif any(label in label_text for label in labels['total_area']):
                        result['total_area'] = safe_float(value)

                    # Перевірка назв для площі кухні
                    elif any(label in label_text for label in labels['kitchen_area']):
                        result['kitchen_area'] = safe_float(value)

        return result


def extract_description_ru(url):
    try:
        response = requests.get(url=url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.text, 'html.parser')
        desc_block = soup.find('div', class_='est-easy-html')
        return desc_block.text.strip().split('http')[0]
    except Exception as ex:
        logger_parser.warning(f'Error dextract ru description - {ex}')
        return ''


def parse_apartment_alan_details(soup):
    # Функція для безпечного перетворення тексту у float
    def safe_float(text):
        try:
            # Видаляємо 'm', 'span' та інші позначки
            cleaned_text = re.sub(r'\s*m\s*<.*?>', '', text).replace(' ', '').replace(',', '.').strip()
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

    # Знаходимо всі блоки параметрів
    param_boxes = soup.find_all('div', class_='param-box text-center')

    # Ініціалізація результату
    result = {
        'rooms_count': None,
        'floor': None,
        'total_floors': None,
        'total_area': None,
        'living_area': None,
        'land_area': None
    }

    # Перебираємо блоки параметрів
    for box in param_boxes:
        text = box.get_text(strip=True)

        # Визначаємо тип параметра за текстом
        if 'Кімнат' in text:
            result['rooms_count'] = safe_int(box.contents[0])

        elif 'Поверха' in text:
            # Якщо є два числа (поверх/поверховість)
            numbers = re.findall(r'\d+', text)
            if len(numbers) >= 2:
                result['floor'] = safe_int(numbers[0])
                result['total_floors'] = safe_int(numbers[1])

        elif 'Площа' in text and 'm' in text:
            result['total_area'] = safe_float(box.contents[0])

        elif 'Житлова' in text and 'm' in text:
            result['living_area'] = safe_float(box.contents[0])

        elif 'Соток' in text:
            result['land_area'] = safe_float(box.contents[0])

    return result

def parse_apartment_alfabrock_details(html_content):
    soup = html_content.find('div', class_='view__props')

    # Функція для безпечного перетворення тексту у float
    def safe_float(text):
        try:
            # Видаляємо нецифрові символи, крім точки та коми
            cleaned_text = re.sub(r'[^\d\s,.]', '', text).replace(' ', '').replace(',', '.')
            return float(cleaned_text)
        except (ValueError, AttributeError):
            return None

    # Функція для безпечного перетворення тексту у int
    def safe_int(text):
        try:
            # Витягуємо число з тексту
            return int(text.strip())
        except (ValueError, TypeError):
            return None

    # Функція для визначення валюти
    def extract_currency(text):
        currency_match = re.search(r'[\$€₴]', text)
        currency_map = {
            '$': 'USD',
            '€': 'EUR',
            '₴': 'UAH'
        }
        return currency_map.get(currency_match.group(), None) if currency_match else None

    # Ініціалізація результату
    result = {
        'total_price': None,
        'price_per_sqm': None,
        'total_area': None,
        'land_area': None,
        'rooms_count': None,
        'total_floors': None,
        'currency': None
    }

    # Знаходимо всі властивості
    props = soup.find_all('div', class_='prop')

    for prop in props:
        value_span = prop.find('span', class_='prop__value')
        label_span = prop

        if not value_span or not label_span:
            continue

        value_text = value_span.get_text(strip=True)
        label_text = label_span.get_text(strip=True).lower()

        # Визначаємо тип властивості
        if 'вартість об' in label_text:
            result['total_price'] = safe_int(value_text)
            result['currency'] = extract_currency(value_text).lower()

        elif 'ціна за м' in label_text:
            result['price_per_sqm'] = safe_float(value_text)

        elif 'м²' in label_text or 'м2' in label_text:
            result['total_area'] = safe_float(value_text)

        elif 'сот' in label_text:
            result['land_area'] = safe_float(value_text)

        elif 'кімнат' in label_text:
            result['rooms_count'] = safe_int(value_text)

        elif 'к-ть поверхів' in label_text or 'поверхів' in label_text:
            result['total_floors'] = safe_int(value_text)

        elif 'поверх' in label_text and '/' in label_text:
            pars_flors = value_text.split('/')
            result['total_floors'] = safe_int(pars_flors[-1])
            result['floor'] = safe_int(pars_flors[0])

    return result


async def extract_full_info_alfabrock(*, session, obj_url, address):
    apartment_details = {'url': obj_url}
    try:

        async with session.get(url=obj_url, headers=headers) as response:
            text = await response.text()
            soup = BeautifulSoup(text, 'lxml')
            try:
                contact_block = soup.find('address', class_='personal__address')
                owner_block = soup.find('div', class_='contact__description')

                profile_block = soup.find('a', attrs={"itemprop":"item"})
                if owner_block:
                    try:
                        apartment_details['owner_name'] = owner_block.h2.text.strip().replace('риелтор -', '')
                    except Exception as ex:
                        logger_parser.warning(f'Alfabrock error owner_name - {ex}')
                else:
                    contact_sub_name = soup.find('div', class_='contact__description')
                    if contact_sub_name:
                        try:
                            apartment_details['owner_name'] = contact_sub_name.h2.text.strip().replace('риелтор -', '')
                        except Exception as ex:
                            logger_parser.warning(f'Alfabrock error name - {ex}')

                if contact_block:
                    try:
                        phone = normalize_ua_phone(contact_block.span.text.strip())
                        apartment_details['phone'] = phone
                    except Exception as ex:
                        logger_parser.warning(f'Alfabrock error phone - {ex}')
                else:
                    contact_sub = soup.find('div', class_='contact__description')
                    if contact_sub:
                        try:
                            phone = normalize_ua_phone(contact_sub.find('p', class_='contact__phone').text.strip())
                            apartment_details['phone'] = phone
                        except Exception as ex:
                            logger_parser.warning(f'Alfabrock error phone - {ex}')

                if profile_block:
                    try:
                        apartment_details['profile_link'] = profile_block.get('href')
                    except Exception as ex:
                        logger_parser.warning(f'Alfabrock error profile link - {ex}')


            except Exception as ex:
                logger_parser.warning(f'Error pars contact allan - {obj_url}. Ex: {ex}')

            images = []
            image_script = soup.find_all('a', class_='swiper-slide')

            if len(image_script) > 0:
                for im in image_script:
                    try:
                        if 'https' not in im.get('href'):
                            images.append('https:' + im.get('href'))
                        else:
                            images.append(im.get('href'))

                    except Exception as ex:
                        logger_parser.warning(f'Photo extr error - {ex}')

                apartment_details['images'] = images

            description_block = soup.find('p', class_='view__secondary')
            if description_block:
                try:
                    description = description_block.get_text(strip=True)

                    apartment_details['description'] = description.replace('\xa0', '')
                except Exception as ex:
                    logger_parser.warning(f'Error description pars allan - {ex}. {obj_url}')

            if address:
                street, house_number = parse_address(address)
                if 'район' not in street:
                    apartment_details['street'] = street if street else None
                    if apartment_details.get('street') and len(house_number) <= 5:
                        apartment_details['house_number'] = house_number

                apartment_details['district'] = address

            apartment_details['title'] = address

            apartment_details['is_realtor'] = 1

            details = parse_apartment_alfabrock_details(html_content=soup)
            apartment_details.update(details)
            price_block = soup.find('div', class_='view__price')
            if price_block:
                clear_price = price_block.text.strip().replace(' ', '').replace(' ', '').replace(r'&nbsp;', '')[:-1]
                if 'млн.' in clear_price:
                    clear_price = clear_price.replace('млн.', '000000')
                price = int(clear_price)
                apartment_details['price'] = price
                if '$' in price_block.text:
                    apartment_details['currency'] = 'USD'
                elif '€' in price_block.text:
                    apartment_details['currency'] = 'EUR'
                else:
                    apartment_details['currency'] = 'UAH'

            if apartment_details.get('price'):
                base_price = await currency_converter.convert_to_uah(apartment_details.get('price'),
                                                               apartment_details.get('currency') or 'UAH')
                apartment_details['base_price'] = base_price
            # print(apartment_details)

            return apartment_details
    except Exception as ex:
        logger_parser.warning(f'error during full_page_info_allan - {ex} - {obj_url}')
        return apartment_details

async def extract_full_info_re_allan(*, session, obj_url, address):
    apartment_details = {'url': obj_url}
    try:

        async with session.get(url=obj_url, headers=headers) as response:
            text = await response.text()
            soup = BeautifulSoup(text, 'lxml')
            try:
                contact_block = soup.find('div', class_='rail-info').find_all('p')
                for n, c in enumerate(contact_block, start=1):
                    if '+380' in c.text:
                        phone = normalize_ua_phone(c.text.strip())
                        apartment_details['phone'] = phone
                    elif 'http' in c.text:
                        apartment_details['profile_link'] = c.text.strip()
                    elif n == 1:
                        apartment_details['owner_name'] = c.text.strip()

            except Exception as ex:
                logger_parser.warning(f'Error pars contact allan - {obj_url}. Ex: {ex}')

            images = []
            image_script = soup.find_all('a', class_='fancybox')

            if len(image_script) > 0:
                for im in image_script:
                    try:
                        if 'https' not in im.get('href'):
                            images.append('https:' + im.get('href'))
                        else:
                            images.append(im.get('href'))

                    except Exception as ex:
                        print(ex)

                apartment_details['images'] = images

            description_block = soup.find('div', class_='obj-descr')
            if description_block:
                try:
                    description = description_block.get_text(strip=True)

                    apartment_details['description'] = description.replace('\xa0', '')
                except Exception as ex:
                    logger_parser.warning(f'Error description pars allan - {ex}. {obj_url}')

            if address:
                street, house_number = parse_address(address)
                if 'район' not in street:
                    apartment_details['street'] = street if street else None
                    if apartment_details.get('street') and len(house_number) <= 5:
                        apartment_details['house_number'] = house_number

                apartment_details['district'] = address

            apartment_details['title'] = address

            apartment_details['is_realtor'] = 1

            details = parse_apartment_alan_details(soup=soup)
            apartment_details.update(details)

            price_block = soup.find('div', class_='full-obj-price')
            if price_block:
                price = int(price_block.text.strip().replace(' ', '').replace(' ', '').replace(r'&nbsp;', '')[:-1])
                apartment_details['price'] = price
                if '$' in price_block.text:
                    apartment_details['currency'] = 'USD'
                elif '€' in price_block.text:
                    apartment_details['currency'] = 'EUR'
                else:
                    apartment_details['currency'] = 'UAH'

            if apartment_details.get('price'):
                base_price = await currency_converter.convert_to_uah(apartment_details.get('price'),
                                                               apartment_details.get('currency') or 'UAH')
                apartment_details['base_price'] = base_price
            # print(apartment_details)

            return apartment_details
    except Exception as ex:
        logger_parser.warning(f'error during full_page_info_allan - {ex} - {obj_url}')
        return apartment_details


async def extract_full_info(*, session, obj_url, address):
    apartment_details = {'url': obj_url}
    try:

        async with session.get(url=obj_url, headers=headers) as response:
            text = await response.text()
            soup = BeautifulSoup(text, 'lxml')
            try:
                contact_block = soup.find_all('div', class_='est-details__content')[1].find_all('div')
                if len(contact_block) == 0:
                    phone = normalize_ua_phone(soup.find_all('div', class_='est-details__content')[1].text)
                    apartment_details['phone'] = phone
                else:
                    for c in contact_block:
                        if c.a:
                            continue

                        if '+380' in c.text:
                            phone = normalize_ua_phone(c.text.strip())
                            apartment_details['phone'] = phone
                        else:
                            apartment_details['owner_name'] = c.text.strip()
            except Exception as ex:
                logger_parser.warning(f'Error pars contact - {obj_url}. Ex: {ex}')

            images = []
            image_script = soup.find_all('a', class_='app__gallery-img')

            if len(image_script) > 0:
                for im in image_script:
                    try:
                        images.append(im.get('data-full'))

                    except Exception as ex:
                        print(ex)

                apartment_details['images'] = images

            description_block = soup.find('div', class_='est-easy-html')
            if description_block:
                try:
                    description = description_block.get_text(strip=True)

                    if 'російській' in description_block.get_text(strip=True):
                        description = extract_description_ru(url=soup.find('div', class_='est-easy-html').find('a').get('href'))
                    else:
                        address_block = description_block.find('div', class_='app__promo-location')
                        description = description.split('http')[0]
                        if address_block:
                            description = description.replace(address_block.text, '')
                    apartment_details['description'] = description.replace('Показать контакты', '').replace('\xa0', '').replace('Показати контакти', '')
                except Exception as ex:
                    logger_parser.warning(f'Error description pars - {ex}. {obj_url}')

            title_block = soup.find('h1', class_='app__h1--supply').get_text(strip=True)

            if address:
                street, house_number = parse_address(address)
                if 'район' not in street:
                    apartment_details['street'] = street if street else None
                    if apartment_details.get('street') and len(house_number) <= 5:
                        apartment_details['house_number'] = house_number

                apartment_details['district'] = address

            apartment_details['title'] = title_block
            apartment_details['is_realtor'] = 1

            status = soup.find('div', class_='contact-status')
            if status:
                if 'господар' in status.text.strip():
                    apartment_details['is_realtor'] = 0

            details = parse_apartment_details(html_content=soup)
            apartment_details.update(details)

            if apartment_details.get('price'):
                base_price = await currency_converter.convert_to_uah(apartment_details.get('price'),
                                                               apartment_details.get('currency') or 'UAH')
                apartment_details['base_price'] = base_price
            # print(apartment_details)

            return apartment_details
    except Exception as ex:
        logger_parser.warning(f'error during full_page_info - {ex} - {obj_url}')
        return apartment_details


def exist_contact(db, author_id, platform='ESTUA'):
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


def create_contact(db, author_id, author_link, is_realtor, author_name, phone, platform='ESTUA'):
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
            cards = soup.find_all('div', class_='eo-item eo-item-supply')
            current_ids = []
            for c in cards:
                try:
                    ad_id = c.get('data-record-id')

                    current_ids.append(ad_id)
                except:
                    pass
            exists_db_ids = models.Offer.get_offers_created_at(ad_ids=current_ids, source='ESTUA')

            for card in cards:
                ad_id = card.get('data-record-id')

                address = card.find('div', class_='eo-item__address').text.strip()
                ad_link = card.find('div', class_='eo-item__address').a.get('href')

                try:

                    if int(ad_id) not in exists_db_ids:
                        if '/go' in ad_link:
                            new_link = get_page_link(url=ad_link)
                            print(f'NEW URL : {new_link}')

                            # re-alan site
                            if 're-alan' in new_link:
                                ads_info = await extract_full_info_re_allan(session=session, obj_url=new_link,
                                                                            address=address.replace('\xa0', ''))

                            # alfabrok site
                            elif 'alfabrok' in new_link:
                                print('extract alfa')
                                ads_info = await extract_full_info_alfabrock(session=session, obj_url=new_link,
                                                                             address=address.replace('\xa0', ''))
                            else:
                                print(f'Skip link - {new_link}')
                                continue

                        else:
                            ads_info = await extract_full_info(session=session, obj_url=ad_link, address=address.replace('\xa0', ''))
                        base_price = ads_info.get('base_price')
                        offer_data = {
                            'ad_id': ad_id,
                            'title': ads_info.get('title'),
                            'owner_type': "business" if ads_info.get('is_realtor') else 'private',
                            'source': 'ESTUA',
                            'price': ads_info.get('price'),
                            'currency': ads_info.get('currency', '').lower(),
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
                            'landmark': None,
                            'ad_link': ad_link,
                            'description': ads_info.get('description'),
                            'main_photo': ads_info.get('images', [None])[0],
                            'photos': ads_info.get('images', []),
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
                            logger_parser.info(f'Create new ads - {ad_id}')
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
                                        "source": "ESTUA",
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
                'url': 'https://est.ua/kiev/nedvizhimost/kupit-kvartiru/?sort=date_up&submitted=1&price_currency=USD',
                'city_id': 10,
                'type': 'apartment',
                'action': 'sale',
            },
            {
                'url': 'https://est.ua/kiev/nedvizhimost/kupit-dom/?sort=date_up&submitted=1&price_currency=USD',
                'city_id': 10,
                'type': 'house',
                'action': 'sale',
            },
            {
                'url': 'https://est.ua/kiev/nedvizhimost/kupit-taunhaus-kvartiru-na-zemle/?sort=date_up&submitted=1&price_currency=USD',
                'city_id': 10,
                'type': 'house',
                'action': 'sale',
            },
            {
                'url': 'https://est.ua/kiev/nedvizhimost/snjat-kvartiru/?sort=date_up&submitted=1&price_currency=USD',
                'city_id': 10,
                'type': 'apartment',
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
