import requests
import logging
from log import logger
from settings import settings

logg = logging.getLogger('log.api_phone_service.py')


def add_task_to_phone(ad_id, user_id, name, is_realtor):
    try:
        response = requests.post(settings.PHONE_API_URL,
                                 json={
                                     "ad_id": ad_id,
                                     "user_id": user_id,
                                     "name": name,
                                     "is_realtor": is_realtor
                                 },
                                 timeout=15)
        logg.info(f'Task response: {response.json()}')
    except Exception as ex:
        logg.warning(f'ad_id: {ad_id}. user_id: {ad_id}. Error {ex}')
