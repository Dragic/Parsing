import logging
import asyncio
import aiohttp
from sqlalchemy import text

import models
from settings import settings
import utils
from datetime import datetime
from database import db_session, DBSession
from log import logger

logg = logging.getLogger('log.olx_views_script.py')

SEMAPHORE = asyncio.Semaphore(8)


async def promoted_ads(ads_id: str, session) -> bool:
    try:
        async with session.get(f'https://www.olx.ua/api/v1/offers/{ads_id}', timeout=15,
                               headers=settings.HEADERS,
                               proxy=settings.PROXY) as response:
            if response.status > 201:
                return False
            data = await response.json()

            return data.get('data', {}).get('promotion', {}).get('top_ad', False)
    except Exception as ex:
        logg.warning(f'Error during execute get promotion for ads id: {ads_id}. Error: {ex}')
        return False


async def extract_data(ads_id: str, obj_id: int, session) -> tuple | None:
    try:
        data = {
            "operationName": "PageViews",
            "variables": {
                "adId": f"{ads_id}"
            },
            "query": "query PageViews($adId: String!) {\n  myAds {\n    pageViews(adId: $adId) {\n      pageViews\n    }\n  }\n}"
        }

        headers = settings.HEADERS
        headers.update({'Authorization': 'ANONYMOUS', 'Site': 'olxua'})
        async with SEMAPHORE:
            try:
                async with session.post('https://production-graphql.eu-sharedservices.olxcdn.com/graphql', timeout=15,
                                        headers=headers,
                                        json=data,
                                        proxy=settings.PROXY) as response:
                    if response.status > 201:
                        logg.warning(f'Bad response olx. Response: {response.status}. ADS: {ads_id} ')
                        return None

                    response_json = await response.json()
                    print(f'OLX Response: {response_json}')
                    page_views = response_json.get('data', {}).get('myAds', {}).get('pageViews', {}).get('pageViews')
                    if isinstance(page_views, int):
                        if page_views == 0:
                            return None
                        is_top = await promoted_ads(ads_id=ads_id, session=session)

                        # Повертаємо дані для батчу
                        return (obj_id, page_views, is_top)
                    else:
                        logg.info(f'Adds already deleted or another error. Ads id: {ads_id}. Obj id: {obj_id}.'
                                  f' Response: {response_json}')
                        return None

            except Exception as ex:
                logg.warning(f'HTTP request error: {ex}')
                return None
    except Exception as ex:
        logg.warning(f'Extract data error: {ex}')
        return None


def bulk_insert_views(views_data):
    if not views_data:
        return False

    # Витягуємо всі id оголошень для запиту
    obj_list = [obj_id for obj_id, _, _ in views_data]

    db = DBSession()
    try:
        latest_views_query = text("""
            SELECT o.offer_id, o.view_count 
            FROM offer_views o
            INNER JOIN (
                SELECT offer_id, MAX(created_at) as latest_date
                FROM offer_views
                WHERE offer_id IN :obj_ids
                GROUP BY offer_id
            ) sub ON o.offer_id = sub.offer_id AND o.created_at = sub.latest_date
        """)

        latest_views_result = db.execute(latest_views_query,
                                         {"obj_ids": tuple(obj_list) if len(obj_list) > 1 else obj_list + [0]})

        # Створюємо словник з останніми переглядами
        previous_views = {row[0]: row[1] for row in latest_views_result}

        # Створюємо список об'єктів для батчового вставлення
        views_objects = []
        for obj_id, page_views, is_top in views_data:
            if not obj_id:
                continue

            # Обчислюємо різницю з попереднім значенням
            previous_view_count = previous_views.get(obj_id, 0)
            view_difference = page_views - previous_view_count if previous_view_count else page_views

            # Створюємо об'єкт з різницею переглядів
            views_objects.append(
                models.OfferViews(
                    offer_id=obj_id,
                    view_count=page_views,
                    view_difference=view_difference,
                    is_top=is_top
                )
            )

        if views_objects:
            # Додаємо всі об'єкти одним батчем
            db.add_all(views_objects)
            db.commit()
            print(f'Created {len(views_objects)} new page views records at: {datetime.now()}')
            return len(views_objects)
        return 0
    except Exception as e:
        logg.warning(f'Bulk database operation error: {e}')
        db.rollback()
        return 0
    finally:
        db.close()


async def main():
    ads_ids = models.Offer.offers_list(period=30, source='OLX')
    print(f'Total find for scanning: {len(ads_ids)}')

    batch_size = 100  # Розмір партії (батча)

    try:
        async with aiohttp.ClientSession() as session:
            for i in range(0, len(ads_ids), batch_size):
                batch = ads_ids[i:i + batch_size]
                tasks = []

                for ads_id, obj_id, _, _, _, _ in batch:
                    tasks.append(extract_data(ads_id=ads_id,
                                              obj_id=obj_id,
                                              session=session)
                                 )

                if tasks:
                    print(f'Processing batch {i // batch_size + 1} with {len(tasks)} tasks...')
                    # Отримуємо результати обробки батчу
                    results = await asyncio.gather(*tasks)

                    # Фільтруємо None та пусті результати
                    valid_results = [result for result in results if result]

                    # Виконуємо батчовий запис у БД безпосередньо, без асинхронного виконання
                    if valid_results:
                        count = bulk_insert_views(valid_results)
                        if count:
                            logg.info(f'Batch {i // batch_size + 1}: Inserted {count} view records')

                    # Додаємо затримку між батчами
                    await asyncio.sleep(0.2)

    except Exception as ex:
        logg.warning(f'* Error main ex:{ex} *')


if __name__ == '__main__':
    start_time = datetime.now()
    logg.info(f'Start Views script - {datetime.now()}')
    asyncio.run(main())
    finish = datetime.now() - start_time
    logg.info(f'Finish Views script - {datetime.now()}. Work at: {finish}')