import requests
import json

from log import logger
import logging
from settings import settings

log = logging.getLogger('log.send_message.py')


def telegram_message(chat_id, text: str, ads_url: str):
    try:
        url = f'https://api.telegram.org/bot{settings.BOT_TOKEN}/sendMessage'

        inline_keyboard = [
            [{
                    "text": "Відкрити оголошення",
                    "url": ads_url
                }]
        ]

        reply_markup = {
            'inline_keyboard': inline_keyboard
        }

        payload_thread = {
            'chat_id': chat_id,
            'parse_mode': 'HTML',
            'disable_web_page_preview': False,
            'text': text,
            'reply_markup': json.dumps(reply_markup)
        }
        response = requests.post(url, data=payload_thread, timeout=5)

        if response.status_code > 201:
            log.warning(f'TELEGRAM send message error - {response.status_code} - {chat_id} - {text}')

        if response.json()['ok'] is False:
            log.info(f'TELEGRAM bad response group - {text} - {response.json()}')
    except Exception as ex:
        log.warning(f'Message - {ex}')
