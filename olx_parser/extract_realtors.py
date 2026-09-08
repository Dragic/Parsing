import json
import logging
import sys
import time
from database import db_session
import models

logg = logging.getLogger('log.export_realtors_without_phone.py')


def export_realtors_without_phone(output_file="realtors_without_phone.json"):
    """
    Вивантажує в JSON файл всіх ріелторів з OLX, у яких немає номера телефону.
    """
    start_time = time.time()

    try:
        with db_session() as session:
            # Отримуємо всіх ріелторів з платформи OLX, у яких phone = Null
            realtors = session.query(models.Realtor).filter(
                models.Realtor.platform == 'OLX',
                models.Realtor.phone.is_(None)
            ).all()

            total_realtors = len(realtors)
            logg.info(f"Знайдено {total_realtors} ріелторів з платформи OLX без телефону")

            # Формуємо словник ріелторів
            realtors_dict = {}

            for realtor in realtors:
                realtors_dict[str(realtor.user_id)] = {
                    "phone": None
                }

            # Зберігаємо в JSON файл
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(realtors_dict, f, ensure_ascii=False, indent=4)

            logg.info(f"Дані успішно збережено у файл {output_file}")

    except Exception as e:
        logg.error(f"Помилка при експорті ріелторів: {str(e)}")
        raise

    execution_time = time.time() - start_time
    logg.info(f"Скрипт виконано за {execution_time:.2f} секунд")

    return {
        'total_realtors': total_realtors,
        'output_file': output_file,
        'execution_time': execution_time
    }


if __name__ == "__main__":
    try:
        logg.info("Початок експорту ріелторів без номерів телефонів")

        # Визначаємо ім'я вихідного файлу (можна передати як аргумент)
        output_file = "realtors_without_phone.json"

        if len(sys.argv) > 1:
            output_file = sys.argv[1]

        result = export_realtors_without_phone(output_file)
        logg.info(f"Результат: експортовано {result['total_realtors']} ріелторів у файл {result['output_file']}")

    except Exception as e:
        logg.error(f"Критична помилка при виконанні скрипта: {str(e)}")
        sys.exit(1)