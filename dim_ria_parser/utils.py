import time
from collections import defaultdict


class SimpleTTLCache:
    def __init__(self, ttl=86400):  # 24h
        self._cache = {}
        self._ttl = ttl

    def add(self, search_key, items):
        """
        Додавання елементів до кешу

        :param search_key: Ключ пошуку
        :param items: Список елементів
        """
        current_time = time.time()
        if search_key not in self._cache:
            self._cache[search_key] = {
                'items': set(items),
                'timestamp': current_time
            }
        else:
            # Оновлення існуючого запису
            self._cache[search_key]['items'].update(items)
            self._cache[search_key]['timestamp'] = current_time

    def filter_new_items(self, search_key, items):
        """
        Фільтрація нових елементів

        :param search_key: Ключ пошуку
        :param items: Список елементів для перевірки
        :return: Список нових елементів
        """
        current_time = time.time()

        # Очищення простроченого кешу
        self._cleanup()

        # Якщо запису немає - всі елементи нові
        if search_key not in self._cache:
            self.add(search_key, items)
            return items

        # Фільтрація нових елементів
        cached_items = self._cache[search_key]['items']
        new_items = [item for item in items if item not in cached_items]

        # Додавання нових елементів до кешу
        if new_items:
            self._cache[search_key]['items'].update(new_items)
            self._cache[search_key]['timestamp'] = current_time

        return new_items

    def _cleanup(self):
        """
        Видалення застарілих записів
        """
        current_time = time.time()
        expired_keys = [
            key for key, value in self._cache.items()
            if current_time - value['timestamp'] > self._ttl
        ]

        for key in expired_keys:
            del self._cache[key]


metro_stations = {
    19: {'name': 'Академмістечко', 'db_id': 1},
    30: {'name': 'Арсенальна', 'db_id': 2},
    23: {'name': 'Берестейська', 'db_id': 3},
    26: {'name': 'Вокзальна', 'db_id': 9},
    32: {'name': 'Гідропарк', 'db_id': 11},
    34: {'name': 'Дарниця', 'db_id': 13},
    31: {'name': 'Дніпро', 'db_id': 55},
    20: {'name': 'Житомирська', 'db_id': 16},
    33: {'name': 'Лівобережна', 'db_id': 24},
    36: {'name': 'Лісова', 'db_id': 25},
    22: {'name': 'Нивки', 'db_id': 29},
    25: {'name': 'Політехнічний інститут', 'db_id': 38},
    21: {'name': 'Святошин', 'db_id': 41},
    28: {'name': 'Театральна', 'db_id': 47},
    27: {'name': 'Університет', 'db_id': 49},
    29: {'name': 'Хрещатик', 'db_id': 51},
    35: {'name': 'Чернігівська', 'db_id': 53},
    24: {'name': 'Шулявська', 'db_id': 54},
    # Зелена гілка
    38: {'name': 'Бориспільська', 'db_id': 4},
    44: {'name': 'Видубичі', 'db_id': 6},
    39: {'name': 'Вирлиця', 'db_id': 7},
    51: {'name': 'Дорогожичі', 'db_id': 15},
    45: {'name': 'Звіринецька', 'db_id': 17},
    49: {'name': 'Золоті ворота', 'db_id': 18},
    47: {'name': 'Кловська', 'db_id': 20},
    50: {'name': "Лук'янівська", 'db_id': 26},
    42: {'name': 'Осокорки', 'db_id': 32},
    48: {'name': 'Палац спорту', 'db_id': 33},
    46: {'name': 'Печерська', 'db_id': 35},
    41: {'name': 'Позняки', 'db_id': 37},
    52: {'name': 'Сирець', 'db_id': 43},
    43: {'name': 'Славутич', 'db_id': 45},
    40: {'name': 'Харківська', 'db_id': 50},
    37: {'name': 'Червоний хутір', 'db_id': 52},
    # Синя гілка
    15: {'name': 'Васильківська', 'db_id': 5},
    16: {'name': 'Виставковий центр', 'db_id': 8},
    1:  {'name': 'Героїв Дніпра', 'db_id': 10},
    14: {'name': 'Голосіївська', 'db_id': 12},
    13: {'name': 'Деміївська', 'db_id': 14},
    17: {'name': 'Іподром', 'db_id': 19},
    6:  {'name': 'Контрактова площа', 'db_id': 21},
    12: {'name': 'Либідська', 'db_id': 23},
    8:  {'name': 'Майдан Незалежності', 'db_id': 27},
    2:  {'name': 'Мінська', 'db_id': 28},
    3:  {'name': 'Оболонь', 'db_id': 30},
    10: {'name': 'Олімпійська', 'db_id': 31},
    11: {'name': 'Палац Україна', 'db_id': 34},
    9:  {'name': 'Площа Українських Героїв', 'db_id': 36},
    4:  {'name': 'Почайна', 'db_id': 39},
    7:  {'name': 'Поштова площа', 'db_id': 40},
    5:  {'name': 'Тараса Шевченка', 'db_id': 46},
    18: {'name': 'Теремки', 'db_id': 48},
}