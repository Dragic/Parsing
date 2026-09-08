import json
import logging

import asyncio
import re

import aiohttp
import models
import ai_repair
from vector_service import api_send_task
import time
import validate_addition_params
from settings import settings
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from database import db_session
from log import logger

# Import the currency converter
from currency_api import currency_converter

logger_main = logging.getLogger('log.main.py')

UPDATE_UNIQUE = settings.UPDATE_ADS
BASE_URL = 'https://100realty.ua'

CITIES_FOR_DUPLICATES = models.City.get_region_city_settings(region_id=10) # Kiev


PLATFORM = '100REALTYUA'


# ── контакти (аналог ria_parser) ─────────────────────────────────────────────

def exist_contact(db, author_id: str, platform: str = PLATFORM):
    """Повертає contact_id якщо вже є в ContactPlatform, інакше None."""
    if not author_id:
        return None
    existing = db.query(models.ContactPlatform).filter(
        models.ContactPlatform.user_id == author_id,
        models.ContactPlatform.platform == platform
    ).first()
    return existing.contact_id if existing else None


def create_contact(db, author_id: str, phone: str, author_name: str,
                   is_realtor: int, author_link: str | None = None,
                   platform: str = PLATFORM):
    """
    Знаходить або створює ContactNew по телефону,
    додає запис ContactPlatform і повертає contact_id.
    """
    existing = db.query(models.ContactNew).filter(
        models.ContactNew.phone == phone
    ).first()

    if existing:
        contact_id = existing.id
    else:
        new_contact = models.ContactNew(
            phone=phone,
            name=author_name,
            is_realtor=is_realtor,
        )
        db.add(new_contact)
        db.flush()
        contact_id = new_contact.id

    platform_contact = models.ContactPlatform(
        contact_id=contact_id,
        platform=platform,
        user_id=author_id,
        name=author_name,
        phone=phone,
        link=author_link,
    )
    db.add(platform_contact)
    db.commit()
    return contact_id


class Stats:
    total_new = 0


stats = Stats()

def city_decode(city: str) -> str:
    if city == 'Чайки':
        city = 'Чайки (Бучанський)'

    elif city == 'Бобриця (Києво-Святошинський)':
        city = 'Бобриця (Бучанський)'

    elif city == 'Буча (місто)':
        city = 'Буча'

    elif city == 'Коцюбинське':
        city = 'Коцюбинське (Київ)'

    elif city == 'Святопетрівське (Петрівське)':
        city = 'Святопетрівське'

    elif city == 'Підгірці':
        city = 'Підгірці (Київ)'

    elif city == 'Ходосівка':
        city = 'Ходосівка (Обухівський)'

    elif city == 'Тарасівка (Києво-Святошинський)':
        city = 'Тарасівка (Обухів)'

    elif city == 'Яблунівка':
        city = 'Яблунівка (Біла Церква)'

    elif city == 'Козин (Конча-Заспа)':
        city = 'Козин (Обухів)'

    elif city == 'В.Солтанівка':
        city = 'Велика Солтанівка'
    elif city == 'Ясногородка (Макарівський)':
        city = 'Ясногородка (Макарів)'

    elif city == 'Погреби (Броварський)':
        city = 'Погреби (Бровари)'

    elif city == 'Вишневе (Києво-Святошинський)':
        city = 'Вишневе'

    elif city == 'Лісне':
        city = 'Лісне (Бучанський)'

    elif city == 'Шевченкове (Києво-Святошинський)':
        city = 'Шевченкове (Бучанський)'

    elif city == 'Калинівка (Броварський)':
        city = 'Калинівка (Бровари)'

    elif city == 'Вишеньки':
        city = 'Вишеньки (Київ)'

    elif city == 'Калинівка (Макарівський)':
        city = 'Калинівка (Макарів)'

    elif city == 'Дмитрівка (Києво-Святошинський)':
        city = 'Дмитрівка (Фастів)'

    elif city == 'Юрівка (Києво-Святошинський)':
        city = 'Юрівка (Фастівський)'

    elif city == 'Калинівка (Васильківський)':
        city = 'Калинівка (Васильків)'

    elif city == 'Петрівське (Бориспільський)':
        city = 'Петропавлівське'

    elif city == 'Михайлівка-Рубежівка':
        city = 'Михайлівка-Рубежівка (Бучанський)'

    elif city == 'Нижня Дубечня':
        city = 'Нижча Дубечня'

    elif city == 'Новосілки (Києво-Святошинський)':
        city = 'Новосілки (Фастівський)'

    elif city == 'Лісники (Києво-Святошинський)':
        city = 'Лісники'
    return city


async def extract_ad(url: str, session, city, obj_type, action) -> dict:
    try:
        try:
            async with session.get(url, timeout=15, headers=settings.HEADERS, proxy=settings.PROXY) as response:
                if response.status > 201:
                    logger_main.warning(f'Bad extract_ad 100rielty. Response: {response.status}. Url: {url} ')
                    return {}

                response_text = await response.text()

        except Exception as ex:
            logger_main.warning(f'HTTP request error: {ex}')
            return {}

        soup = BeautifulSoup(response_text, 'html.parser')
        ad_id = url.split('/')[-1]
        price = int(soup.find('div', class_='price').text.replace('* грн.', '').replace('грн.', '').replace(' ', '').strip())

        title = soup.find('h1').text
        rooms_count = soup.find('div', attrs={'id': 'object-rooms'})
        if rooms_count:
            number = re.findall(r'\d+', rooms_count.text)
            if number:
                rooms_count = int(number[0])

        object_squares = soup.find('div', attrs={'id': 'object-squares'})
        if object_squares:
            number = re.findall(r'\d+(?:\.\d+)?', object_squares.text)
            if number:
                object_squares = float(number[0])

        object_squares_com = soup.find('div', attrs={'id': 'object-squares2'})
        if object_squares_com:
            number = re.findall(r'\d+(?:\.\d+)?', object_squares_com.text)
            if number:
                object_squares_com = float(number[0])

        object_sqrtotal = soup.find('div', attrs={'id': 'object-sqrtotal'})
        living_area = None
        if object_sqrtotal:
            number = re.findall(r'\d+(?:\.\d+)?', object_sqrtotal.text)
            if number:
                object_sqrtotal = float(number[0])
                if len(number) > 2:
                    living_area = float(number[1])


        indicators__markers = soup.find_all('span', class_='indicators__marker')
        no_commission = None
        e_oselya = None
        for marker in indicators__markers:
            if marker:
                if 'Без комісії' in marker.text:
                    no_commission = True
                if 'єОселя' in marker.text:
                    e_oselya = True

        if obj_type == 'house' and object_sqrtotal:
            object_squares = object_sqrtotal

        if obj_type == 'commercial' and object_squares_com:
            object_squares = object_squares_com

        floors = soup.find('div', attrs={'id': 'object-floors'})
        floor = None
        total_floors = None
        if floors:
            try:
                floors_text = floors.find("div", class_="value").get_text(strip=True)  # "8/18"
                if "/" in floors_text:
                    floor, total_floors = floors_text.split("/")
                    floor = int(floor)
                    total_floors = int(total_floors)
                else:
                    total_floors = int(floors_text)
            except:
                floor = None
                total_floors = None

        materials = soup.find('div', attrs={'id': 'object-materials'})
        if materials:
            materials = materials.text.split(':')[-1].strip()

        repair = None
        repair_block = soup.find('div', attrs={'id': 'object-levels'})
        if repair_block:
            repair = repair_block.text

        photos = soup.find_all('a', attrs={'data-fancybox': 'realty-object-photo'})
        img = []
        for p in photos:
            img.append(p.get('href'))

        script_obj = soup.find('script', attrs={'type': 'application/ld+json'}).text

        phone = None
        author_id = None
        drupal_settings = soup.find('script', attrs={'data-drupal-selector': 'drupal-settings-json'})
        if drupal_settings:
            try:
                drupal_json = json.loads(drupal_settings.text)
                phone = drupal_json["object_phones"][0][::-1].replace('(', '').replace(')', '').replace(' ', '').replace('-', '').strip()
                author_id = phone.replace('+3', '')
            except:
                pass


        script_json = json.loads(script_obj)
        # print(script_json)
        dt_str = script_json.get('@graph', [{}, {}])[0].get('offers', {}).get('priceValidUntil')

        if dt_str:
            refresh_time = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        else:
            refresh_time = datetime.now()

        furniture = soup.find('div', class_='object-furniture') # меблі
        if furniture:
            furniture = furniture.text

        description = soup.find('div', class_='object-total-info').text.strip()
        contact_block = soup.find('div', class_='object-contact-information').text

        user_name = contact_block.split('\n')[-1].strip()
        author_link = soup.find('a', class_='all-user-objects')#.get('href')
        if author_link:
            author_link = author_link.get('href')

        img = []
        main_photo = None

        # print(furniture)
        is_realtor = 1 if 'Посередник' in contact_block else 0

        breadcrumbs_content = soup.find('div', class_='breadcrumbs__content').find_all('a')
        if city == 'Київ':
            district = breadcrumbs_content[-2].text.replace('район', '').strip()
            street = breadcrumbs_content[-1].text.replace('Продаж квартири', '')
            street_full = title.split('/')[0].split('вул.')[-1].replace(f'в Києві', '').strip()

            match = re.match(r"(.+?)\s+(\d[\w\/]*)$", street_full)
            if match:
                street_name = street
                house_number = match.group(2).strip()
            else:
                street_name = street
                house_number = None
        else:
            district = None

            city = breadcrumbs_content[-1].text
            street_full = title.split('/')[0].split('вул.')[-1].replace(f'{city}', '').replace('Продаж квартири', '').strip()

            match = re.match(r"(.+?)\s+(\d[\w\/]*)$", street_full)
            if match:
                street_name = f'вул. {match.group(1).strip()}'
                house_number = match.group(2).strip()
            else:
                street_name = street_full
                house_number = ""

        # for breadcrumbs in breadcrumbs_content:
        #     print(breadcrumbs.text)

        for n, photo in enumerate(photos):
            if n == 0:
                main_photo = photo.get('href')
            img.append(photo.get('href'))

        map_position = soup.find('div', attrs={"id": 'object-map'})
        if map_position:
            longitude = map_position.get("data-lng")
            latitude = map_position.get("data-lat")
        else:
            longitude = None
            latitude = None

        city = city_decode(city)
        print(
            f"Title: {title}\n"
            f"author_link: {author_link}\n"
            f"contact: {user_name}\n"
            f"main_photo: {main_photo}\n"
            f"Ad ID: {ad_id}\n"
            f"Price: {price}\n"
            f"Repair: {repair}\n"
            f"phone: {phone}\n"
            f"author_id: {author_id}\n"
            f"Rooms: {rooms_count}\n"
            f"Square: {object_squares}\n"
            f"total_floors: {floor}/{total_floors}\n"
            f"Materials: {materials}\n"
            f"district : {district}\n"
            f"street : {street_name}\n"
            f"house_number : {house_number}\n"
            f"furniture : {furniture}\n"
            f"refresh_time : {refresh_time}\n"
            f"is_realtor : {is_realtor}\n"

        )
        return {
                        'ad_id': ad_id,
                        'title': title,
                         "no_commission":no_commission,
                         "e_oselya": e_oselya,
                        'living_area': living_area,
                        'city': city,
                        'author_id': author_id,
                        'phone': phone,
                        'district': district,
                        'owner_type': 'business' if is_realtor else 'private',
                        'source': '100REALTYUA',
                        'price': price,
                        'currency': 'uah',
                        'type': obj_type,
                        'action': action,

                        'street': None if obj_type == 'land' else street_name,
                        'house_number': None if obj_type == 'land' else house_number,
                        'floors': total_floors,
                        'floor': floor,
                        'total_area': object_squares,
                        'rooms': rooms_count,
                        'latitude': latitude,
                        'longitude': longitude,
                        'ad_link': url,
                        'description': description,
                        'main_photo': main_photo,
                        'photos': img,
                        'refresh_time': refresh_time,

                    }

    except Exception as ex:
        logger_main.warning(f'Extract data error - {ex}. - {url}')
        return {}


async def extract_data(url: str, obj_type, action, city_region, city_dict, session) -> bool:
    news_offers = []
    try:
        try:
            async with session.get(url, timeout=15, headers=settings.HEADERS, proxy=settings.PROXY) as response:
                print(response.status)
                if response.status > 201:
                    logger_main.warning(f'Bad response 100rielty. Response: {response.status}. Url: {url} ')
                    return False

                response_text = await response.text()

        except Exception as ex:
            logger_main.warning(f'HTTP request error: {ex}')
            return False

        soup = BeautifulSoup(response_text, 'html.parser')

        print(f'Pars url - {url} - {city_region}')
        ads_list = soup.find_all('div', class_='object-address')
        current_ids = [ad.a.get('href').split('/')[-1] for ad in ads_list]
        exists_db_ids = models.Offer.get_offers_created_at(ad_ids=current_ids, source='100REALTYUA')

        for ad in ads_list:
            try:
                obj_id = int(ad.a.get('href').split('/')[-1])
                if obj_id not in exists_db_ids:
                    ad_link = BASE_URL + ad.a.get('href')

                    obj_data = await extract_ad(url=ad_link, session=session, city=city_region, obj_type=obj_type, action=action)
                    district_id = None
                    city_id = city_dict.get(obj_data.get('city'), {}).get('id')
                    if city_id:
                        district_obj = city_dict.get(obj_data.get('city'), {}).get(f"{obj_data.get('district')}")
                        if district_obj:
                            district_id = district_obj.get('id')

                    if city_id is None:
                        logger_main.info(f'city_id not found - {obj_data} - {ad.a.get("href")}\n\n')
                        continue

                    # ── контакт ───────────────────────────────────────────
                    contact_id = None
                    author_id  = obj_data.get('author_id')
                    phone      = obj_data.get('phone')
                    if author_id and phone:
                        try:
                            with db_session() as db:
                                contact_id = exist_contact(db=db, author_id=author_id)
                                if contact_id is None:
                                    contact_id = create_contact(
                                        db=db,
                                        author_id=author_id,
                                        phone=phone,
                                        author_name=obj_data.get('author_name') or '',
                                        is_realtor=1 if obj_data.get('owner_type') == 'business' else 0
                                    )
                        except Exception as ex:
                            logger_main.warning(f'Contact create error ad_id={obj_data.get("ad_id")}: {ex}')

                    obj_data['contact_id'] = contact_id
                    # прибираємо службові поля перед збереженням
                    obj_data.pop('author_id', None)
                    obj_data.pop('phone',     None)
                    obj_data.pop('author_name', None)
                    # ─────────────────────────────────────────────────────

                    obj_data.update({'district_id': district_id, 'city_id': city_id, 'region_id': 10})

                    obj_data.pop('city', None)
                    obj_data.pop('district', None)
                    if obj_data.get('action') == 'sale':
                        obj_data['repair'] = '1' if await ai_repair.has_repair(
                            obj_data.get('description')) else None

                    if obj_type == 'house':
                        obj_data['property_type_houses'] = validate_addition_params.detect_property_type_houses(
                            text=obj_data.get('description'))

                    obj_data['no_commission'] = validate_addition_params.detect_no_commission(
                        text=obj_data.get('description'))

                    news_offers.append(obj_data)
                    logger_main.info(f'Add new obj - {obj_data.get("ad_id")}')
                    stats.total_new += 1

            except Exception as ex:
                logger_main.warning(f'Error during pars link - {ex}')

        return True
    except Exception as ex:
        logger_main.warning(f'Extract data error - {ex}')
        return False
    finally:

        # batch create offers
        if news_offers:
            result = models.Offer.bulk_create_offers(offers_data=news_offers, source='100REALTYUA')
            logger_main.info(f'Result created offer: - {result}')
            if result:
                for offer in news_offers:
                    try:

                        if offer.get('action') == 'sale' and offer.get('city_id') in CITIES_FOR_DUPLICATES and offer.get(
                                'type') in ['apartment', 'house']:
                            db_id = result.get('created_ad_ids', {}).get(offer.get('ad_id'))
                            if db_id and CITIES_FOR_DUPLICATES.get(offer.get('city_id'), {}).get('detect_photo_duplicates'):
                                await api_send_task({
                                    "ad_id": offer.get('ad_id'),
                                    "db_id": db_id,  # pk
                                    "action": offer.get('action'),
                                    "source": "100REALTYUA",
                                    "type_obj": offer.get('type'),
                                    "city_id": offer.get('city_id'),
                                    "base_price": offer.get('price'),
                                    "created_at": int(datetime.now().timestamp())
                                })
                                logger_main.info(f'Send obj to vector service api - {offer.get("ad_id")}. db_id = {db_id}')
                    except:
                        pass


async def start_parsing_rielty():
    start = datetime.now()
    logger_main.info(f'Start parser - {datetime.now()}')
    city_dict = models.City.get_districts_by_region_grouped(region_id=10)
    allowed_links = [
        {
            'obj_type': 'apartment',
            'action': 'sale',
            'city': 'Київ',
            'url': 'https://100realty.ua/uk/realty_search/apartment/sale/cur_3/kch_2/sort/id_asc#realty-search-sort',
        },
        {
            'obj_type': 'apartment',
            'action': 'sale',
            'city': 'Область',
            'url': 'https://100realty.ua/uk/realty_search/apartment/sale/cur_3/kch_1/sort/id_asc#realty-search-sort',
        },
        {
            'obj_type': 'house',
            'action': 'sale',
            'city': 'Київ',
            'url': 'https://100realty.ua/uk/realty_search/house/sale/cur_3/kch_2/sort/id_asc#realty-search-sort',
        },
        {
            'obj_type': 'house',
            'action': 'sale',
            'city': 'Область',
            'url': 'https://100realty.ua/uk/realty_search/house/sale/cur_3/kch_1/sort/id_asc#realty-search-sort',
        },
        {
            'obj_type': 'commercial',
            'action': 'sale',
            'city': 'Київ',
            'url': 'https://100realty.ua/uk/realty_search/nonlive/sale/cur_3/kch_2/sort/id_asc#realty-search-sort',
        },
        {
            'obj_type': 'commercial',
            'action': 'sale',
            'city': 'Область',
            'url': 'https://100realty.ua/uk/realty_search/nonlive/sale/cur_3/kch_1/sort/id_asc#realty-search-sort',
        },
        {
            'obj_type': 'land',
            'action': 'sale',
            'city': 'Київ',
            'url': 'https://100realty.ua/uk/realty_search/land/sale/cur_3/kch_2/sort/id_asc#realty-search-sort',
        },
        {
            'obj_type': 'land',
            'action': 'sale',
            'city': 'Область',
            'url': 'https://100realty.ua/uk/realty_search/land/sale/cur_3/kch_1/sort/id_asc#realty-search-sort',
        },

        {
            'obj_type': 'apartment',
            'action': 'rent',
            'city': 'Київ',
            'url': 'https://100realty.ua/uk/realty_search/apartment/rent/cur_3/kch_2/sort/id_asc#realty-search-sort',
        },
        {
            'obj_type': 'apartment',
            'action': 'rent',
            'city': 'Область',
            'url': 'https://100realty.ua/uk/realty_search/apartment/rent/cur_3/kch_1/sort/id_asc#realty-search-sort',
        },

        {
            'obj_type': 'house',
            'action': 'rent',
            'city': 'Київ',
            'url': 'https://100realty.ua/uk/realty_search/house/rent/cur_3/kch_2/sort/id_asc#realty-search-sort',
        },
        {
            'obj_type': 'house',
            'action': 'rent',
            'city': 'Область',
            'url': 'https://100realty.ua/uk/realty_search/house/rent/cur_3/kch_1/sort/id_asc#realty-search-sort',
        },

        {
            'obj_type': 'commercial',
            'action': 'rent',
            'city': 'Київ',
            'url': 'https://100realty.ua/uk/realty_search/nonlive/rent/cur_3/kch_2/sort/id_asc#realty-search-sort',
        },
        {
            'obj_type': 'commercial',
            'action': 'rent',
            'city': 'Область',
            'url': 'https://100realty.ua/uk/realty_search/nonlive/rent/cur_3/kch_1/sort/id_asc#realty-search-sort',
        },
    ]
    try:

        async with aiohttp.ClientSession() as session:
            for pars_obj in allowed_links:
                await extract_data(url=pars_obj.get('url'),
                                   obj_type=pars_obj.get('obj_type'),
                                   action=pars_obj.get('action'),
                                   city_region=pars_obj.get('city'),
                                   city_dict=city_dict,
                                   session=session)

    except Exception as ex:
        logger_main.warning(f'* Error start_parsing_realty: - ex:{ex} *')

    finish = datetime.now() - start
    logger_main.info(f'Finish parser - {datetime.now()}. Work at {finish} ')


async def main_loop():
    while True:
        try:
            print(f'Start pars... Use proxy: {settings.PROXY}')

            # Update currency exchange rates at the start of each parsing cycle
            logger_main.info("Updating currency exchange rates...")
            await currency_converter.update_exchange_rates()

            stats.total_new = 0
            await start_parsing_rielty()
            logger_main.info(
                f'ADD new ads {stats.total_new}.\nSleeping for 15 minutes before next parsing cycle')
            from datetime import datetime, time

            # поточний UTC час
            how_hour = datetime.utcnow().hour

            if how_hour in [x for x in range(4, 20)]:
                await asyncio.sleep(60 * 15)  # sleep seconds
            else:
                await asyncio.sleep(60 * 45)

        except Exception as e:
            logger_main.error(f'Critical error in main loop: {str(e)}')
            logger_main.info(f'Sleeping for 60 seconds after error before retrying')
            await asyncio.sleep(60)


if __name__ == '__main__':
    try:
        logger_main.info("Starting continuous monitoring service")
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger_main.info("Service manually stopped")
    except Exception as e:
        logger_main.error(f"Fatal error: {str(e)}")