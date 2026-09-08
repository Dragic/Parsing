import requests
import logging
from log import logger
import re

def clean_street(street: str) -> str:
    # видаляє слеш і все, що після нього
    return re.sub(r'[\\/].*$', '', street).strip()


logg = logging.getLogger('log.location_api.py')


def get_location(*, city_id, street):
    try:

        street = clean_street(street)
        response = requests.get(
            f'https://allvart.com/api/geocoder/{city_id}/search/{street}',
            headers={'X-API-Key': '16658af72c226baca04a2bbc0c1db122d819aa0cf141ed3c2fa70a435a31b6e2'},
            timeout=15
        )

        if response.ok:
            data = response.json().get('data', {})

            if len(data) >= 1:
                location = next(iter(data.values()))
                return {
                    'microdistrict_id': location.get('microdistrict_id', None),
                    'lat': location.get('lat'),
                    'street': location.get('road'),
                    'lon': location.get('lon')
                }

        return {}

    except Exception as ex:
        logg.warning(f'city_id: {city_id}. street: {street}. Error {ex}')
        return {}
