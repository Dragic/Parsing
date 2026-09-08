import requests
import logging
from log import logger
from settings import settings

log = logging.getLogger('log.vector_service.py')


async def api_send_task(data: dict):
    try:
        response = requests.post(settings.VECTOR_API_URL, json=data, timeout=15)
        log.warning(f'API response - {response.status_code}')
        if response.status_code == 422:
            log.info(f'{data}')
    except Exception as ex:
        log.warning(f'Error during send vector api - {ex}. {data}')
