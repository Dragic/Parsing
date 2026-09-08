import logging
import asyncio
from curl_cffi import requests
import models
from settings import settings
import utils
from datetime import datetime
from database import db_session, DBSession
from log import logger

# Import the currency converter
from currency_api import currency_converter


logg = logging.getLogger('log.olx_deleted_at_script.py')

IMPERSONATE = 'chrome'
EXTRA_HEADERS = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'accept-language': 'uk-UA,uk;q=0.9,ru;q=0.8,en-US;q=0.7,en;q=0.6',
}

SEMAPHORE = asyncio.Semaphore(8)


async def extract_data(ads_id: str, price: int | None, obj_id: int, session, promotion, ad_link, current_currency) -> int | None:
    try:
        headers = {**settings.HEADERS, **EXTRA_HEADERS}
        async with SEMAPHORE:
            try:
                response = session.get(
                    f'https://www.olx.ua/api/v1/offers/{ads_id}',
                    timeout=15,
                    headers=headers,
                    proxy=settings.PROXY,
                    impersonate=IMPERSONATE,
                )
                print(f'OLX RESPONSE ({ads_id}) by id: {response.status_code}')
                if response.status_code > 201 and response.status_code != 403:

                    # add log deleted ads
                    models.OfferLog.log_change(offer_id=obj_id, change_type='deleted', value='1')

                    # Повертаємо id об'єкта для подальшого батчового оновлення
                    return obj_id

                if response.status_code == 200:
                    res_data = response.json()
                    ad = res_data['data']
                    if ad:
                        ad_url = ad['url']
                        if ad_url != ad_link:
                            models.Offer.update(id=obj_id,
                                                ad_link=ad_url)

                    new_value_promotion = res_data['data'].get('promotion', {}).get('top_ad', False)
                    if 'params' in ad:
                        for param in ad['params']:
                            if param['key'] == 'price' and param['value']:
                                current_price = param['value'].get('value')
                                currency = param['value'].get('currency')
                                if current_price != price or currency.lower() != current_currency:
                                    base_price = current_price

                                    if current_price is not None:
                                        base_price = await currency_converter.convert_to_uah(current_price, currency or 'UAH')

                                    print(f'Price change current - {current_price} new price - {price}')
                                    # add log to change price
                                    models.OfferLog.log_change(offer_id=obj_id,
                                                               change_type='price_change',
                                                               value=f"{current_price}",
                                                               details=f'{price}')

                                    # update current ads to new price
                                    models.Offer.update(id=obj_id,
                                                        price=current_price,
                                                        base_price=base_price,
                                                        currency=currency.lower(),
                                                        is_top=new_value_promotion)

                    if new_value_promotion != promotion:
                        models.OfferLog.log_change(offer_id=obj_id,
                                                   change_type='is_top',
                                                   value=f"1" if new_value_promotion else '0')
                        if current_price == price:
                            # update if price the same
                            models.Offer.update(id=obj_id,  is_top=new_value_promotion)

                return None

            except Exception as ex:
                logg.warning(f'HTTP request error: {ex}')
                return None
    except Exception as ex:
        logg.warning(f'Extract data error: {ex}')
        return None


# Функція для батчового оновлення deleted_at
def bulk_update_deleted_at(obj_ids):
    if not obj_ids:
        return False

    db = DBSession()
    try:
        # Отримуємо поточну дату/час
        now = datetime.now()

        # Оновлюємо всі записи одним запитом
        count = db.query(models.Offer).filter(
            models.Offer.id.in_(obj_ids)
        ).update(
            {models.Offer.deleted_at: now, models.Offer.is_top: False},
            synchronize_session=False
        )

        db.commit()
        print(f'Updated {count} records as deleted at: {now}')
        return count
    except Exception as e:
        logg.warning(f'Bulk database update error: {e}')
        db.rollback()
        return None
    finally:
        db.close()


async def main():
    await currency_converter.update_exchange_rates()

    batch_size = 100
    total_processed = 0
    batch_num = 0

    try:
        with requests.Session(impersonate=IMPERSONATE) as session:
            for batch in models.Offer.offers_list_batches(period=32, source='OLX', batch_size=batch_size):
                batch_num += 1
                total_processed += len(batch)

                tasks = [
                    extract_data(
                        ads_id=ads_id,
                        obj_id=obj_id,
                        price=price,
                        session=session,
                        promotion=is_top,
                        ad_link=ad_link,
                        current_currency=currency,
                    )
                    for ads_id, obj_id, price, is_top, ad_link, currency in batch
                ]

                print(f'Try run {len(tasks)} tasks from batch {batch_num}...')
                results = await asyncio.gather(*tasks, return_exceptions=True)

                valid_ids = [
                    obj_id for obj_id, res in zip((t[1] for t in batch), results)
                    if res and not isinstance(res, Exception)
                ]
                # (якщо extract_data сама повертає obj_id при успіху — просто фільтруй results як і було:
                # valid_ids = [r for r in results if r and not isinstance(r, Exception)])

                if valid_ids:
                    count = bulk_update_deleted_at(valid_ids)
                    if count:
                        logg.info(f'Batch {batch_num}: Updated {count} offers as deleted')

                await asyncio.sleep(0.2)

    except Exception as ex:
        logg.warning(f'* Error main ex:{ex} *')

    print(f'Total processed: {total_processed}')


if __name__ == '__main__':
    start_time = datetime.now()
    logg.info(f'Start Delete at OLX script - {datetime.now()}')
    asyncio.run(main())
    finish = datetime.now() - start_time
    logg.info(f'Finish Delete at OLX script - {datetime.now()}. Work at: {finish}')