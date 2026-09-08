from settings import settings
from openai import OpenAI, AsyncOpenAI
import time
import logging
import json
from log import logger

logg = logging.getLogger('log.ai_agent.py')


client = AsyncOpenAI(api_key=settings.OPEN_AI_TOKEN)


AI_EXTRACTABLE_FIELDS_KYIV = [
    'street', 'house_number', 'subway_id', 'residential_complex',
    'floors', 'floor', 'total_area', 'heating', 'repair'
]

AI_EXTRACTABLE_FIELDS_REGION = [
    'street', 'house_number', 'residential_complex',
    'floors', 'floor', 'total_area', 'heating', 'repair'
]


async def addition_params(input_msg: str,
                          version=settings.PROMPT_VERSION,
                          prompt_id=settings.PROMPT_ID) -> dict:
    try:
        response = await client.responses.create(
            prompt={
                "id": prompt_id,
                "version": version
            },

            tools=[{"type": "web_search"}],
            input='Формат відповіді JSON. \n\n' + input_msg
        )
        data = json.loads(response.output_text)
        return data
    except Exception as ex:
        logg.warning(f'Error - {ex}. Input: {input_msg}')

    return {}

