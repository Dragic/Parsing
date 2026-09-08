import asyncio
import aiohttp
import time

HEADERS = {
        'User-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
        'Priority': '',
        'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7,uk;q=0.6',
        'Authority': 'dom.ria.com',
    }

async def get_ads_list(session, search: str, page='') -> list:
    try:
        search = search.split('?')[-1]
        new_ads = []

        async with session.get(
                f'https://dom.ria.com/node/searchEngine/v2/?{search}{page}',
                timeout=15,
                headers=HEADERS
        ) as response:
            if response.status > 200:
                time.sleep(20)
                return []

            data = await response.json()

            # Фільтрація елементів через кеш
            print(data["items"])
            return data["items"]
    except Exception as ex:
        print(ex)

async def find_ad_in_search(search: str, target_id: int):
    async with aiohttp.ClientSession() as session:

        for page in range(1, 342):  # 341 сторінка
            page_param = f"&page={page}"

            ads = await get_ads_list(session, search, page_param)

            if not ads:
                continue

            for ad in ads:
                if ad == target_id:
                    print(f"Found on page {page}")
                    return page

            print(f"Checked page {page}")

    print("Ad not found")
    return None

RIA_OBJ_URL = {
        'rent': {
            'apartment': [
                'https://dom.ria.com/uk/search/?excludeSold=1&category=1&realty_type=2&operation=3&state_id=RIA_STATE_ID&price_cur=1&wo_dupl=1&sort=created_at&period=per_allday&photos_count_from=3&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&ch=246_244'
            ],
            'house': [
                'https://dom.ria.com/uk/search/?excludeSold=1&category=4&realty_type=0&operation=3&state_id=RIA_STATE_ID&price_cur=1&wo_dupl=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&ch=246_244'
            ],
            'commercial': [
                'https://dom.ria.com/uk/search/?excludeSold=1&category=13&realty_type=0&operation=3&state_id=RIA_STATE_ID&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&ch=242_240,247_252'
            ],
            'room': [
                'https://dom.ria.com/uk/search/?excludeSold=1&category=40&realty_type=0&operation=3&state_id=RIA_STATE_ID&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&ch=226_223,242_239,247_252'
            ],
            'garage': [
                'https://dom.ria.com/uk/search/?excludeSold=1&category=30&realty_type=0&operation=3&state_id=RIA_STATE_ID&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&ch=226_223,242_239,247_252'
            ]
        },
        'sale': {
            'apartment': [
                # 'https://dom.ria.com/uk/search/?excludeSold=1&category=1&realty_type=2&operation=1&state_id=RIA_STATE_ID&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&wo_dupl=1&ch=242_239,247_252',
                'https://dom.ria.com/uk/search/?excludeSold=1&category=1&realty_type=2&operation=1&state_id=RIA_STATE_ID&price_cur=1&newbuildings=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&wo_dupl=1&ch=209_f_3,209_t_0,242_239,247_252',
                'https://dom.ria.com/uk/search/?excludeSold=1&category=1&realty_type=2&operation=1&state_id=RIA_STATE_ID&price_cur=1&newbuildings=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&wo_dupl=1&ch=209_f_1,209_t_1,242_239,247_252',
                'https://dom.ria.com/uk/search/?excludeSold=1&category=1&realty_type=2&operation=1&state_id=RIA_STATE_ID&price_cur=1&newbuildings=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&wo_dupl=1&ch=209_f_2,209_t_2,242_239,247_252',

                'https://dom.ria.com/uk/search/?excludeSold=1&category=1&realty_type=2&operation=1&state_id=RIA_STATE_ID&price_cur=1&secondary=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&wo_dupl=1&ch=209_f_3,209_t_0,242_239,247_252',
                'https://dom.ria.com/uk/search/?excludeSold=1&category=1&realty_type=2&operation=1&state_id=RIA_STATE_ID&price_cur=1&secondary=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&wo_dupl=1&ch=209_f_1,209_t_1,242_239,247_252',
                'https://dom.ria.com/uk/search/?excludeSold=1&category=1&realty_type=2&operation=1&state_id=RIA_STATE_ID&price_cur=1&secondary=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&wo_dupl=1&ch=209_f_2,209_t_2,242_239,247_252',

            ],
            'house': [
                # 'https://dom.ria.com/uk/search/?excludeSold=1&category=4&realty_type=0&operation=1&state_id=RIA_STATE_ID&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&wo_dupl=1&ch=226_223,242_239,247_252'
                'https://dom.ria.com/uk/search/?excludeSold=1&category=4&realty_type=0&operation=1&state_id=RIA_STATE_ID&newbuildings=1&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&wo_dupl=1&ch=226_223,242_239,247_252'
                'https://dom.ria.com/uk/search/?excludeSold=1&category=4&realty_type=0&operation=1&state_id=RIA_STATE_ID&secondary=1&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&wo_dupl=1&ch=226_223,242_239,247_252'
            ],
            'land': [
                'https://dom.ria.com/uk/search/?excludeSold=1&category=24&realty_type=0&operation=1&state_id=RIA_STATE_ID&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&ch=226_223,242_239,251_248'
            ],
            'commercial': [
                'https://dom.ria.com/uk/search/?excludeSold=1&category=13&realty_type=0&operation=1&state_id=RIA_STATE_ID&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&ch=226_223,242_239,247_252'
            ],
            'room': [
                'https://dom.ria.com/uk/search/?excludeSold=1&category=40&realty_type=0&operation=1&state_id=RIA_STATE_ID&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&ch=226_223,242_239,247_252'
            ],
            'garage': [
                'https://dom.ria.com/uk/search/?excludeSold=1&category=30&realty_type=0&operation=1&state_id=RIA_STATE_ID&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&ch=226_223,242_239,247_252'
            ]
        }
    }

# для парсингу всіх міст
async def process_city_many(region_obj: dict):
    try:
        print(f'Start region - {region_obj.get("region_name")}')

        region_id = region_obj.get('region_id')


        obj_links = settings.RIA_OBJ_URL

        async with aiohttp.ClientSession() as session:
            for action in obj_links:
                if action == 'rent':
                    continue
                for type_obj, list_url in obj_links[action].items():
                    for url in list_url:
                        for page in range(1, 101):
                            try:
                                page_param = f"&page={page}"
                                ads_ids = await get_ads_list(session=session,
                                                             search=url.replace('RIA_STATE_ID', f'{region_id}'), page=page_param)

                                # pars ads
                                tasks = [extract_data(ad_id=ad_id,
                                                      property_type=type_obj,
                                                      action=action,
                                                      region_obj=region_obj,
                                                      session=session) for ad_id in ads_ids]
                                await asyncio.gather(*tasks)
                            except:
                                pass

    except Exception as ex:
        logg.warning(f'* Error region parsing: {region_obj.get("region_name")} - ex:{ex} *')


if __name__ == '__main__':
    asyncio.run(find_ad_in_search(search='https://dom.ria.com/uk/search/?excludeSold=1&category=1&realty_type=2&operation=1&state_id=10&price_cur=1&sort=created_at&firstIteraction=false&limit=100&market=3&type=map&without_entity_group=1&client=searchV2&wo_dupl=1&ch=242_239,247_252', target_id=34043546))