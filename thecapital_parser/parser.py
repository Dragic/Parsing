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

logger_parser = logging.getLogger('log.thecapital_parser.py')


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


def generate_title(data: dict, action: str) -> str:
    rooms = data.get('rooms')
    area = data.get('area')
    floor = data.get('floor')
    floor_count = data.get('floors')
    obj_type = data.get('type')

    action_str = 'Оренда' if action == 'rent' else 'Продаж'

    type_map = {
        'apartment': 'квартири',
        'house': 'будинку',
        'land': 'ділянки'
    }

    type_str = type_map.get(obj_type, 'нерухомості')

    rooms_str = f'{rooms}-кімн.' if rooms else 'Студія'

    parts = [action_str, type_str]

    if obj_type == 'apartment':
        parts.append(rooms_str)

    if area:
        parts.append(f'{area} м²')

    if floor and floor_count and obj_type == 'apartment':
        parts.append(f'{floor}/{floor_count} пов.')

    return ' '.join(parts)


async def parse_card(session: aiohttp.ClientSession, url: str) -> dict:
    async with session.get(url=url, headers=headers) as response:
        text = await response.text()

    soup = BeautifulSoup(text, 'html.parser')


    # --- price + currency ---
    # <div class="apartment__header-sum"><span>149 317</span><p>USD</p></div>
    base_price = None
    price = None
    currency = 'USD'
    price_el = soup.select_one('.apartment__header-sum span')
    currency_el = soup.select_one('.apartment__header-sum p')
    if price_el:
        price_raw = price_el.get_text(strip=True).replace('\xa0', '').replace(' ', '')
        price = int(price_raw) if price_raw.isdigit() else None
    if currency_el:
        currency = currency_el.get_text(strip=True) or 'USD'

    if price and currency:
        base_price = await currency_converter.convert_to_uah(price, currency or 'UAH')

    # --- total_area + rooms ---
    # <div class="apartment__body-info-title-item-sum">70 м²</div>
    # <div class="apartment__body-info-title-item-sum">1 кімн.</div>
    total_area = None
    rooms = None
    for el in soup.select('.apartment__body-info-title-item-sum'):
        text = el.get_text(strip=True)
        if 'м²' in text:
            num = re.sub(r'[^\d.]', '', text)
            total_area = float(num) if num else None
        elif 'кімн' in text:
            num = re.sub(r'[^\d]', '', text)
            rooms = int(num) if num else None

    # --- floor / floors ---
    # <div class="apartment__mobile-info-item"><span class="icon-city"></span><p>3/25</p></div>
    floor, floors = None, None
    for item in soup.select('.apartment__mobile-info-item'):
        if item.select_one('.icon-city'):
            p = item.select_one('p')
            if p:
                m = re.match(r'(\d+)/(\d+)', p.get_text(strip=True))
                if m:
                    floor = int(m.group(1))
                    floors = int(m.group(2))
            break

    # --- street + house_number ---
    # <div class="apartment__body-info-item-title">Вулиця</div>
    # <div class="apartment__body-info-item-text">Залізничне, 45а</div>
    street, house_number = None, None
    for item in soup.select('.apartment__body-info-item'):
        title_el = item.select_one('.apartment__body-info-item-title')
        text_el = item.select_one('.apartment__body-info-item-text')
        if title_el and text_el and 'Вулиця' in title_el.get_text():
            raw = text_el.get_text(strip=True)  # "Залізничне, 45а"
            parts = raw.split(',', 1)
            street = parts[0].strip() if parts else None
            house_number = parts[1].strip() if len(parts) > 1 else None
            break

    # --- residential_complex ---
    residential_complex = None
    for item in soup.select('.apartment__body-info-item'):
        title_el = item.select_one('.apartment__body-info-item-title')
        text_el = item.select_one('.apartment__body-info-item-text')
        if title_el and text_el and title_el.get_text(strip=True) == 'ЖК':
            rc = text_el.get_text(strip=True)
            # Ігноруємо "Окремий будинок /не ЖК"
            if rc and 'не ЖК' not in rc and 'Окремий' not in rc:
                residential_complex = rc
            break

    # --- description ---
    # Текст знаходиться в .os-content (scrollable div з описом)
    description = None
    desc_el = soup.find('div', class_='apartment__body-info-about-text')
    if desc_el:
        description = desc_el.get_text(separator='\n', strip=True)

    # --- photos ---
    # Тільки великі фото з основного слайдера (не мініатюри)
    # <a href="https://...jpg" data-fancybox="gallery" class="apartment__body-slider-item swiper-slide ...">
    photos = []
    seen = set()
    for a in soup.select('.apartment__body-slider-big a[data-fancybox="gallery"]'):
        href = a.get('href')
        if href and href not in seen and not href.endswith('1x1.png'):
            seen.add(href)
            photos.append(href)
    main_photo = photos[0] if photos else None

    offer_data = {
        'source': 'THECAPITAL',
        'owner_type': 'business',
        'is_realtor': True,
        'price': price,
        'currency': currency.lower(),
        'base_price': base_price,
        'total_area': total_area,
        'rooms': rooms,
        'floor': floor,
        'floors': floors,
        'street': street,
        'house_number': house_number,
        'city_name': 'Київ',         # thecapital.com.ua — тільки Київ
        'residential_complex': residential_complex,
        'description': description,
        'main_photo': main_photo,
        'photos': photos,
        'ad_link': url,
        'updated_at': datetime.utcnow(),
        'created_at': datetime.utcnow(),
        'refresh_time': datetime.utcnow(),
    }
    return offer_data


async def get_new_data(*, session, obj_data):
    try:
        async with session.get(url=obj_data.get('url'), headers=headers) as response:
            text = await response.text()

        soup = BeautifulSoup(text, 'html.parser')
        page_cards = soup.find_all('div', class_='apartment-item swiper-slide')

        current_ids = [x.get('data-id') for x in page_cards]

        ids = models.Offer.get_offers_created_at(ad_ids=current_ids, source='THECAPITAL')

        for card in page_cards:
            try:
                ad_id = card.get('data-id')

                if ad_id and int(ad_id) not in ids:

                    offer_data = await parse_card(session=session, url=card.find('a', class_='apartment-item__img').get('href'))

                    if offer_data.get('main_photo') is None:
                        continue

                    offer_data['ad_id'] = ad_id
                    offer_data['type'] = obj_data.get('type')

                    offer_data['action'] = obj_data.get('action')
                    offer_data['title'] = generate_title(data=offer_data, action=obj_data.get('action'))

                    if obj_data.get('action') == 'sale':
                        offer_data['repair'] = '1' if await ai_repair.has_repair(offer_data.get('description')) else None


                    offer_data['city_id'] = 10
                    offer_data['region_id'] = 10

                    if offer_data.get('type') == 'house':
                        offer_data['property_type_houses'] = validate_addition_params.detect_property_type_houses(
                            text=offer_data.get('description'))

                    offer_data['no_commission'] = validate_addition_params.detect_no_commission(
                        text=offer_data.get('description'))

                    address_block = card.find('div', class_='apartment-item__info-static-text')
                    if address_block:
                        district = address_block.text.strip()
                        district_id = district_pars(district)
                        offer_data['district_id'] = district_id

                    with db_session() as db:

                        offer_data.pop('city_name')
                        base_price = offer_data.pop('base_price')

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
                                "source": "THECAPITAL",
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
                'url': 'https://thecapital.com.ua/search-result/?_city=kiev&_type=kvartira&_status=prodazh&_per_page=34&_sort=date_desc',
                'region_id': 10,
                'city_id': 10,
                'type': 'apartment',
                'action': 'sale',
            },
            {
                'url': 'https://thecapital.com.ua/search-result/?_city=kiev&_type=commercial&_status=prodazh&_per_page=34&_sort=date_desc',
                'region_id': 10,
                'city_id': 10,
                'type': 'commercial',
                'action': 'sale',
            },
            {
                'url': 'https://thecapital.com.ua/search-result/?_city=kiev&_type=budynok&_status=prodazh&_per_page=34&_sort=date_desc',
                'region_id': 10,
                'city_id': 10,
                'type': 'house',
                'action': 'sale',
            },
            {
                'url': 'https://thecapital.com.ua/search-result/?_city=kiev&_type=zemelni-dilyanky&_status=prodazh&_per_page=34&_sort=date_desc',
                'region_id': 10,
                'city_id': 10,
                'type': 'land',
                'action': 'sale',
            },

            {
                'url': 'https://thecapital.com.ua/search-result/?_city=kiev&_type=kvartira&_status=orenda&_per_page=34&_sort=date_desc',
                'region_id': 10,
                'city_id': 10,
                'type': 'apartment',
                'action': 'rent',
            },
            {
                'url': 'https://thecapital.com.ua/search-result/?_city=kiev&_type=budynok&_status=orenda&_per_page=34&_sort=date_desc',
                'region_id': 10,
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
