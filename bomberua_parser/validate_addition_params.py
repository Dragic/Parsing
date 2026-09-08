PROPERTY_TYPE_HOUSES_MAP = {
    'Клубний будинок': 'club_house',
    'Частина будинку': 'house_part',
    'Модульні будинки': 'modular_homes',
    'Кантрі хаус': 'country_house',
    'Таунхаус': 'townhouse',
    'Котедж': 'cottage',
    'Дуплекс': 'duplex',
    'Дача': 'country_house',
}


def detect_property_type_houses(text: str) -> str | None:
    if not text:
        return None
    lower = text.lower()
    for key, value in PROPERTY_TYPE_HOUSES_MAP.items():
        if key.lower() in lower:
            return value
    return None


# Ключові фрази, які вказують на відсутність комісії
COMMISSION_TYPE = {
    "без комісії": True,
    "без комиссии": True,
    "комісія 0%": True,
    "комиссия 0%": True,
    "0% комісії": True,
    "0% комиссии": True,
}


def detect_no_commission(text: str) -> bool | None:
    if not text:
        return None

    lower = text.lower()

    for key, value in COMMISSION_TYPE.items():
        if key in lower:
            return value
    return None
