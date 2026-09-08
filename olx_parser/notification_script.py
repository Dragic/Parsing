import logging
import asyncio
import aiohttp
import models
from settings import settings
import utils
from datetime import datetime
from database import db_session, DBSession
from log import logger

logg = logging.getLogger('log.notification_script.py')

SEMAPHORE = asyncio.Semaphore(8)


async def extract_data(ads_id: str, session) -> dict:
    result = {}
    headers = settings.HEADERS
    try:
        async with session.get(f'https://www.olx.ua/api/v1/offers/{ads_id}', timeout=15,
                               headers=headers,
                               proxy=settings.PROXY) as response:
            print(f'OLX RESPONSE ({ads_id}) by id: {response.status}')
            if response.status > 201 and response.status != 403:
                # add log deleted ads
                result['deleted'] = 1
                return result
            if response.status == 200:
                res_data = await response.json()
                ad = res_data['data']
                is_top = res_data['data'].get('promotion', {}).get('top_ad', False)
                result['is_top'] = is_top
                if 'params' in ad:
                    for param in ad['params']:
                        if param['key'] == 'price' and param['value']:
                            current_price = param['value'].get('value')
                            currency = param['value'].get('currency')

                            result['price_change'] = current_price
                            result['currency'] = currency

            return result

    except Exception as ex:
        logg.warning(f'HTTP request error: {ex}')
        return result


async def api_notification(session, log_id):
    try:
        async with session.post(f'{settings.API_HOST}/api/parser/log/{log_id}', timeout=15,
                                headers={'Authorization': f'{settings.API_TOKEN}'},
                                json={}) as response:

            logg.warning(f'Response api {response.status}. log_id: {log_id}')
            resp = await response.json()
            logg.warning(f'Response resp {resp}. log_id: {log_id}')
    except Exception as ex:
        logg.warning(f'Error during send api request - {log_id}. {ex}')


async def main():
    offers_id = models.UserOfferTracking.get_all_tracking_records()
    logg.warning(f'Total find for scanning: {len(offers_id)}')
    try:
        async with aiohttp.ClientSession() as session:
            for offer_id in offers_id:
                try:
                    ads = models.Offer.get_offer(offer_id=offer_id)
                    if not ads:
                        logg.warning(f'Adds not found for source olx - {offer_id}')
                        continue
                    logg.warning(f"Get: {ads.get('ad_id')}")
                    response = await extract_data(ads_id=ads.get('ad_id'), session=session)
                    logg.info(f"Response offer_id: {offer_id} = {response}")

                    if response:

                        notification_keys = offers_id[offer_id]
                        logg.warning(f'{offer_id} notification_keys: {notification_keys}')
                        for key in notification_keys:

                            # перевіряємо чи повернулось значення
                            if key in response:
                                if key == 'deleted':
                                    current_state = models.Offer.get_offer(offer_id=offer_id)

                                    if current_state.get('deleted_at') is None:
                                        models.Offer.update(id=offer_id, is_top=False, deleted_at=datetime.now())
                                        log_id = models.OfferLog.log_change(offer_id=offer_id, change_type='deleted', value='1')
                                        await api_notification(session=session, log_id=log_id)

                                if key == 'price_change':
                                    if response.get('price_change') != ads.get('price'):
                                        # offers.base_price was dropped; the price is stored in the
                                        # ad's own currency, so keep the two columns in step.
                                        # main.py stores the OLX currency lower-cased — match it.
                                        new_currency = response.get('currency')
                                        changes = {'price': response.get('price_change')}
                                        if new_currency:
                                            changes['currency'] = new_currency.lower()

                                        models.Offer.update(id=offer_id, **changes)

                                        log_id = models.OfferLog.log_change(offer_id=offer_id,
                                                                            change_type='price_change',
                                                                            value=f"{response.get('price_change')}",
                                                                            details=f"{ads.get('price')}")
                                        await api_notification(session=session, log_id=log_id)

                                if key == 'is_top':
                                    if response.get('is_top') != ads.get('is_top'):
                                        models.Offer.update(id=offer_id, is_top=response.get('is_top'))

                                        log_id = models.OfferLog.log_change(offer_id=offer_id,
                                                                            change_type='is_top',
                                                                            value=f"1" if response.get('is_top') else '0')
                                        await api_notification(session=session, log_id=log_id)
                except Exception as ex:
                    logg.warning(f'Error during update offer_id: {offer_id}- {ex}')
            await asyncio.sleep(0.2)

    except Exception as ex:
        logg.warning(f'* Error main ex:{ex} *')


if __name__ == '__main__':
    start_time = datetime.now()
    logg.info(f'Start Notification script - {datetime.now()}')
    asyncio.run(main())
    finish = datetime.now() - start_time
    logg.info(f'Finish Notification script - {datetime.now()}. Work at: {finish}')
