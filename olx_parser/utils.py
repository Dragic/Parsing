from settings import settings


def generate_links_list(city_id: int, categories_id: int, currency: str) -> dict:
    links = {
        'business': [],
        'private': []
    }
    business_links = []
    private_links = []

    base_link = settings.OLX_API_BASE_LINK.\
        replace('OLX_CATEGORIES', f"{categories_id}").\
        replace('OLX_CITY', f"{city_id}").\
        replace('OLX_SORT', 'filter_float_price%3Aasc')

    for p in range(1, 200_000, 20_000):

        for offset in range(0, 1050, 50):
            business_links.append(
                base_link.replace('OLX_CURRENCY', currency).replace('OLX_OFFSET', f'{offset}').replace('OLX_OWNER_TYPE',
                                                                                                    'business').replace(
                    'OLX_START_PRICE', f"{p}"))

            private_links.append(
                base_link.replace('OLX_CURRENCY', currency).replace('OLX_OFFSET', f'{offset}').replace('OLX_OWNER_TYPE',
                                                                                                    'private').replace(
                    'OLX_START_PRICE', f"{p}"))

    links['business'] = business_links
    links['private'] = private_links

    return links


def generate_links_list_monitoring(region_olx_id: int, categories_id: int, currency: str) -> list:
    links = []

    base_link = settings.OLX_API_BASE_LINK.\
        replace('OLX_CATEGORIES', f"{categories_id}").\
        replace('OLX_SORT', 'created_at%3Adesc')\
        .replace("OLX_START_PRICE", '1')\
        .replace('&city_id=OLX_CITY', f'&region_id={region_olx_id}')

    for offset in range(0, 150, 50):
        links.append(
                base_link
                .replace('OLX_CURRENCY', currency)
                .replace('OLX_OFFSET', f'{offset}')
                .replace('&owner_type=OLX_OWNER_TYPE', ''))
    return links


def generate_links_list_monitoring_realtors(region_olx_id: int, categories_id: int, currency: str, users) -> list:
    links = []
    for user in users:
        base_link = settings.OLX_API_BASE_LINK.\
            replace('OLX_CATEGORIES', f"{categories_id}").\
            replace('OLX_SORT', 'created_at%3Adesc')\
            .replace('&city_id=OLX_CITY', f'&region_id={region_olx_id}&user_id={user}')

        for offset in range(0, 50, 50):
            links.append(
                    base_link
                    .replace('OLX_CURRENCY', currency)
                    .replace('OLX_OFFSET', f'{offset}')
                    .replace('&owner_type=OLX_OWNER_TYPE', '').replace("OLX_START_PRICE", '1')
            )

            # links.append(
            #     base_link
            #     .replace('OLX_CURRENCY', currency)
            #     .replace('OLX_OFFSET', f'{offset}')
            #     .replace('OLX_OWNER_TYPE', 'business').replace("OLX_START_PRICE", '7000')
            # )

            # links.append(
            #     base_link
            #     .replace('OLX_CURRENCY', currency)
            #     .replace('OLX_OFFSET', f'{offset}')
            #     .replace('OLX_OWNER_TYPE', 'business').replace("OLX_START_PRICE", '15000')
            # )


    return links


