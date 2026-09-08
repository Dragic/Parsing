import sys
import time
from datetime import datetime
from database import db_session
import models
import requests
from settings import settings
import logging

logg = logging.getLogger('log.realtors_link_parser.py')


def extract_olx_author_url(session: requests.Session, user_id: int):
    try:
        response = session.get(f'https://www.olx.ua/api/v1/users/{user_id}/', headers=settings.HEADERS, timeout=15)
        if response.status_code > 300:
            logg.warning(f'Error olx response code: {response.status_code} for user id: {user_id}')
            time.sleep(60)
            return (None, None)

        user = response.json()['data']
        return (user.get('user_ads_url', None), user.get('name', None))
    except Exception as ex:
        logg.warning(f'Error extract_olx_author_url: {ex}')
        return (None, None)


def update_realtors_url(batch_size=20):
    updated_count = 0
    client_session = requests.Session()

    try:
        with db_session() as session:

            # Отримуємо всіх рієлторів з платформи OLX, у яких не вказаний URL
            realtors = session.query(models.ContactPlatform).filter(
                models.ContactPlatform.platform == 'OLX',
                models.ContactPlatform.user_id.isnot(None),
                models.ContactPlatform.link.is_(None)
            ).all()

            logg.info(f"Знайдено {len(realtors)} рієлторів без URL")

            # Обробляємо кожного рієлтора
            for i, realtor in enumerate(realtors, 1):
                print(f'{i}: {realtor.user_id}')
                # Генеруємо URL на основі ID користувача
                new_url, name = extract_olx_author_url(session=client_session, user_id=realtor.user_id)

                if new_url:
                    print(f'New name: {name}. URl: {new_url}')
                    realtor.link = new_url
                    realtor.name = name
                    realtor.updated_at = datetime.now()
                    updated_count += 1

                    logg.debug(f"Оновлено URL для рієлтора ID {realtor.id}: {new_url}")

                    # Зберігаємо зміни кожні batch_size записів
                    if i % batch_size == 0:
                        session.commit()
                else:
                    logg.warning(f"Не вдалося створити URL для рієлтора ID {realtor.id} (user_id: {realtor.user_id})")

            # Комітимо залишок змін
            if updated_count % batch_size != 0:
                session.commit()

            logg.info(f"Всього оновлено {updated_count} з {len(realtors)} записів")

    except Exception as e:
        logg.error(f"Помилка при оновленні URL рієлторів: {str(e)}")
        raise

    # закриття сесії request
    client_session.close()

    return updated_count


if __name__ == "__main__":
    try:
        logg.info("Початок оновлення URL рієлторів OLX")

        # Можна вказати розмір батчу через аргумент командного рядка
        batch_size = 100
        if len(sys.argv) > 1:
            try:
                batch_size = int(sys.argv[1])
            except ValueError:
                logg.warning(f"Невірний розмір батчу: {sys.argv[1]}."
                             f" Буде використано значення за замовчуванням: {batch_size}")

        updated = update_realtors_url(batch_size)
        time.sleep(0.2)

        logg.info(f"Оновлення URL рієлторів OLX завершено успішно. Оновлено {updated} записів.")

    except Exception as e:
        logg.error(f"Критична помилка при виконанні скрипта: {str(e)}")
        sys.exit(1)
