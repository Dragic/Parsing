import logging
import sys
import time
import random
from collections import Counter
from database import db_session
import models
import requests
from settings import settings

logg = logging.getLogger('log.list_realtors_without_city.py')


def extract_city_ids(session: requests.Session, user_id: int):
    """
    Отримує список ID міст з оголошень користувача через API OLX

    Args:
        session (requests.Session): Сесія для HTTP запитів
        user_id (int): ID користувача на OLX

    Returns:
        list: Список ID міст з оголошень користувача
    """
    cities_ids = []
    try:
        response = session.get(f'https://www.olx.ua/api/v1/offers/?offset=0&limit=50&user_id={user_id}&category_id=1',
                               headers=settings.HEADERS, timeout=15)
        ads_list = response.json()['data']
        for ads in ads_list:
            city_id = ads.get('location', {}).get('city', {}).get('id')
            if city_id is not None:  # Додаємо перевірку на None
                cities_ids.append(city_id)
        return cities_ids
    except Exception as ex:
        logg.warning(f'extract_city_ids - {ex} user: {user_id}')
        return cities_ids


def determine_most_common_city(city_ids):
    """
    Визначає ID міста, яке зустрічається найчастіше в списку.
    Якщо є кілька міст з однаковою (найбільшою) кількістю оголошень,
    обирає одне з них випадковим чином.

    Args:
        city_ids (list): Список ID міст

    Returns:
        int or None: ID міста з найбільшою кількістю оголошень або None, якщо список порожній
    """
    if not city_ids:
        return None

    # Підраховуємо кількість оголошень для кожного міста
    city_counts = Counter(city_ids)

    # Знаходимо максимальну кількість оголошень
    max_count = max(city_counts.values())

    # Знаходимо всі міста з максимальною кількістю оголошень
    top_cities = [city for city, count in city_counts.items() if count == max_count]

    # Якщо є кілька міст з максимальною кількістю, обираємо випадкове
    if len(top_cities) > 1:
        chosen_city = random.choice(top_cities)
        return chosen_city
    else:
        return top_cities[0]


def list_and_update_realtors_without_city(batch_size=100, update_db=True):
    """
    Ітерує по всіх ріелторах, де platform = 'OLX' і city_id = None,
    визначає місто з найбільшою кількістю оголошень і оновлює запис в БД.

    Args:
        batch_size (int): Розмір партії для обробки
        update_db (bool): Чи зберігати зміни в базі даних
    """
    start_time = time.time()
    total_realtors = 0
    updated_realtors = 0
    skipped_realtors = 0
    client_session = requests.Session()

    try:
        with db_session() as session:
            # Отримуємо загальну кількість ріелторів без міста
            count_query = session.query(models.Realtor).filter(
                models.Realtor.platform == 'OLX',
                models.Realtor.city_id.is_(None)
            ).count()

            logg.info(f"Знайдено {count_query} ріелторів з platform='OLX' і city_id=None")

            # Отримуємо ріелторів порціями
            offset = 0
            while True:
                realtors_batch = session.query(models.Realtor).filter(
                    models.Realtor.platform == 'OLX',
                    models.Realtor.city_id.is_(None)
                ).order_by(
                    models.Realtor.id
                ).limit(batch_size).offset(offset).all()

                if not realtors_batch:
                    break

                for realtor in realtors_batch:
                    total_realtors += 1

                    # Отримуємо ID міст з оголошень ріелтора
                    cities_list = extract_city_ids(session=client_session, user_id=realtor.user_id)

                    # Визначаємо найчастіше місто
                    most_common_city = determine_most_common_city(cities_list)

                    if most_common_city:
                        # Перевіряємо, чи існує місто в нашій базі даних
                        olx_city = session.query(models.City).filter(
                            models.City.olx_id == most_common_city
                        ).first()

                        if olx_city:
                            print(
                                f"ok: ID={realtor.id}, user_id={realtor.user_id}, встановлено city_id={olx_city.id} (olx_id={most_common_city})")

                            # Оновлюємо запис в БД
                            if update_db:
                                realtor.city_id = olx_city.id
                                updated_realtors += 1
                        else:
                            print(
                                f"skipped: ID={realtor.id}, user_id={realtor.user_id}, olx_city_id={most_common_city} не знайдено в БД")
                            skipped_realtors += 1
                    else:
                        print(f"skipped: ID={realtor.id}, user_id={realtor.user_id}, не знайдено міст в оголошеннях")
                        skipped_realtors += 1

                # Комітимо зміни після кожної партії
                if update_db:
                    session.commit()

                offset += batch_size
                logg.info(f"Оброблено {min(offset, count_query)} з {count_query} ріелторів")

            logg.info(f"Всього оброблено {total_realtors} ріелторів")
            if update_db:
                logg.info(f"Оновлено city_id для {updated_realtors} ріелторів")
            logg.info(f"Пропущено {skipped_realtors} ріелторів (не знайдено відповідного міста)")

    except Exception as e:
        logg.error(f"Помилка при обробці ріелторів: {str(e)}")
        raise

    execution_time = time.time() - start_time
    logg.info(f"Скрипт виконано за {execution_time:.2f} секунд")


if __name__ == "__main__":
    try:
        logg.info("Початок обробки ріелторів без вказаного міста")

        # Параметри за замовчуванням
        batch_size = 100
        update_db = True  # За замовчуванням оновлюємо БД

        # Перевіряємо аргументи командного рядка
        if len(sys.argv) > 1:
            try:
                batch_size = int(sys.argv[1])
            except ValueError:
                logg.warning(f"Невірний розмір партії: {sys.argv[1]}. Буде використано значення за замовчуванням: 100")

        list_and_update_realtors_without_city(batch_size, update_db)

    except Exception as e:
        logg.error(f"Критична помилка при виконанні скрипта: {str(e)}")
        sys.exit(1)
