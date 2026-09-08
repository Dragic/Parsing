import logging
import asyncio
import urllib.parse

import aiohttp
import models
from settings import settings

from datetime import datetime
from log import logger


logg = logging.getLogger('log.check_position_scrit.py')


async def is_delete(ads_id: str, session) -> bool:
    headers = settings.HEADERS
    try:
        async with session.get(f'https://www.olx.ua/api/v1/offers/{ads_id}', timeout=15, headers=headers) as response:
            print(f'OLX RESPONSE is_delete ({ads_id}) by id: {response.status}')
            if response.status > 201 and response.status != 403:
                # deleted
                return True

            if response.status == 403:
                # block
                print(f'Sleep... BAD REQUEST - {response.status}')
                await asyncio.sleep(300)

            return False

    except Exception as ex:
        logg.warning(f'HTTP request error: {ex}')
        return False


async def extract_data(*, ads_id: str,
                       session: aiohttp.ClientSession,
                       search_query: str,
                       city_id: int,
                       limit=200
                       ) -> dict:
    result = {'status': 'not_found', 'value': 0}
    position = 0
    found = False

    headers = settings.HEADERS
    encoded_text = urllib.parse.quote(search_query)
    base_url = f'https://www.olx.ua/api/v1/offers/?offset=0&limit=50&query={encoded_text}&city_id={city_id}&currency=UAH&sort_by=relevance%3Adesc&filter_refiners=spell_checker&facets=%5B%7B%22field%22%3A%22district%22%2C%22fetchLabel%22%3Atrue%2C%22fetchUrl%22%3Atrue%2C%22limit%22%3A30%7D%5D'
    try:
        for offset in range(0, limit + 1, 50):
            url = base_url.replace("offset=0", f"offset={offset}")
            async with session.get(url, timeout=15, headers=headers) as response:
                print(f'OLX RESPONSE ({ads_id}) by id: {response.status} offset {offset}\nURL: {url}')
                if response.status == 200:
                    res_data = await response.json()
                    ads_list = res_data['data']
                    for ad in ads_list:

                        position += 1
                        if ad.get('id') == ads_id:
                            result.update({'status': 'found', 'value': position})
                            found = True
                            break
            if found:
                break

            # sleep after request
            print(f'sleep 5 sec  after request offset {offset}...')
            await asyncio.sleep(5)

        return result

    except Exception as ex:
        logg.warning(f'HTTP request error: {ex}')
        return result


async def main():
    keywords = models.Keyword.get_active_keywords()
    print(f'Total find for scanning: {len(keywords)}\n{keywords}')
    try:
        async with aiohttp.ClientSession() as session:
            for row in keywords:
                try:
                    ads = models.Offer.check_olx_offer(ad_id=row.get('advert_id'))
                    if not ads:
                        logg.warning(f'Ads deleted in db: {row.get("advert_id")} not found for source olx or deleted')
                        models.Keyword.update_status(keyword_id=row.get("id"), new_status='disabled')
                        models.KeywordLog.add_log(keyword_id=row.get("id"), status='error', value=0)
                        continue

                    deleted = await is_delete(ads_id=row.get("advert_id"), session=session)
                    if deleted:
                        logg.warning(f'Ads deleted from olx: {row.get("advert_id")} not found for source olx or deleted')
                        models.Keyword.update_status(keyword_id=row.get("id"), new_status='disabled')
                        models.KeywordLog.add_log(keyword_id=row.get("id"), status='error', value=0)
                        continue

                    print(f"Pars ad {ads}")
                    city_olx_id = models.City.get_city(city_id=ads)
                    response = await extract_data(ads_id=row.get('advert_id'),
                                                  search_query=row.get('keyword'),
                                                  city_id=city_olx_id,
                                                  session=session,
                                                  limit=200)

                    if response:
                        models.KeywordLog.add_log(keyword_id=row.get("id"),
                                                  status=response.get('status'),
                                                  value=response.get('value'))
                        logg.info(f'Create new row - for {row.get("advert_id")} - {response}')

                except Exception as ex:
                    logg.warning(f'Error during update row: {row}- {ex}')
            await asyncio.sleep(0.2)

    except Exception as ex:
        logg.warning(f'* Error main ex:{ex} *')


if __name__ == '__main__':
    start_time = datetime.now()
    logg.info(f'Start Position script - {datetime.now()}')
    asyncio.run(main())
    finish = datetime.now() - start_time
    logg.info(f'Finish Position script - {datetime.now()}. Work at: {finish}')
