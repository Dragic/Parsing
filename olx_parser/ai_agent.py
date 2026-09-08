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

ALLOWED_HEATING = {
    "centralized",
    "own_boiler-house",
    "individual_gas",
    "individual_electro",
    "solid_fuel",
    "heat_pump",
    "combined",
    "other"
}

ALLOWED_REPAIR = {1, 2, 3, 4, 5, 6, 7}

ALLOWED_SUBWAY = {
    1,2,3,9,11,13,55,16,24,25,29,38,41,47,49,51,53,54,
    4,6,7,15,17,18,20,26,32,33,35,37,43,45,50,52,
    5,8,10,12,14,19,21,23,27,28,30,31,34,36,39,40,46,48
}

def check_fields(ai_results: dict) -> dict:

    result = {}

    for k, v in ai_results.items():

        if v is None:
            result[k] = None
            continue

        if k == "heating":
            result[k] = v if v in ALLOWED_HEATING else None

        elif k == "repair":
            try:
                v = int(v)
                result[k] = v if v in ALLOWED_REPAIR else None
            except:
                result[k] = None

        elif k == "subway_id":
            try:
                v = int(v)
                result[k] = v if v in ALLOWED_SUBWAY else None
            except:
                result[k] = None

        elif k in {"floor", "floors"}:
            try:
                result[k] = int(v)
            except:
                result[k] = None

        elif k == "total_area":
            try:
                result[k] = float(str(v).replace(",", "."))
            except:
                result[k] = None

        else:
            result[k] = v

    return result


async def addition_params(input_msg: str,
                          version=settings.PROMPT_VERSION,
                          prompt_id=settings.PROMPT_ID) -> dict:
    resp = ''
    try:
        response = await client.responses.create(
            prompt={
                "id": prompt_id,
                "version": version
            },

            input='Формат відповіді JSON. \n\n' + input_msg
        )
        resp = response.output_text
        data = json.loads(response.output_text)
        clear_data = check_fields(data)
        return clear_data
    except Exception as ex:
        logg.warning(f'Error - {ex}. Input: {input_msg}. Resp: {resp}')

    return {}

