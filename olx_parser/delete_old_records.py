import logging
import sys
from datetime import datetime, timedelta
from sqlalchemy import delete, or_, func
from database import db_session
from models import RawOffer, Offer
from log import logger
import logging

logg = logging.getLogger('log.delete_old_records.py')


def cleanup_old_records_raw():
    """
    Видалення записів з таблиці RawOffers, які старіші за 3 місяці.
    Функція використовує або created_at або updated_at для визначення віку запису.
    """
    try:
        # Визначаємо дату, яка була 6 місяці тому
        three_months_ago = datetime.now() - timedelta(days=180)

        with db_session() as session:
            # Підраховуємо загальну кількість записів перед видаленням
            total_records = session.query(func.count(RawOffer.id)).scalar()

            # Підраховуємо кількість записів, які будуть видалені
            records_to_delete = session.query(func.count(RawOffer.id)).filter(
                or_(
                    RawOffer.created_at < three_months_ago
                )
            ).scalar()

            # Видаляємо записи, які старіші за 3 місяці
            delete_query = delete(RawOffer).where(
                or_(
                    RawOffer.created_at < three_months_ago
                )
            )

            session.execute(delete_query)
            session.commit()

            # Отримуємо кількість записів після видалення
            remaining_records = session.query(func.count(RawOffer.id)).scalar()

            logger.info(f"Завершено видалення застарілих записів з RawOffers")
            logger.info(f"Загальна кількість записів до видалення: {total_records}")
            logger.info(f"Видалено записів: {records_to_delete}")
            logger.info(f"Залишилось записів: {remaining_records}")

            return {
                'total_before': total_records,
                'deleted': records_to_delete,
                'remaining': remaining_records
            }

    except Exception as e:
        logg.error(f"Помилка при видаленні записів: {str(e)}")
        raise


def cleanup_old_records_offer():
    """
    Видалення записів з таблиці RawOffers, які старіші за 3 місяці.
    Функція використовує або created_at або updated_at для визначення віку запису.
    """
    try:
        # Визначаємо дату, яка була 3 місяці тому
        three_months_ago = datetime.now() - timedelta(days=90)

        with db_session() as session:
            # Підраховуємо загальну кількість записів перед видаленням
            total_records = session.query(func.count(RawOffer.id)).scalar()

            # Підраховуємо кількість записів, які будуть видалені
            records_to_delete = session.query(func.count(Offer.id)).filter(
                or_(
                    Offer.created_at < three_months_ago
                )
            ).scalar()

            # Видаляємо записи, які старіші за 3 місяці
            delete_query = delete(Offer).where(
                or_(
                    Offer.created_at < three_months_ago
                )
            )

            session.execute(delete_query)
            session.commit()

            # Отримуємо кількість записів після видалення
            remaining_records = session.query(func.count(Offer.id)).scalar()

            logger.info(f"Offer Завершено видалення застарілих записів з RawOffers")
            logger.info(f"Offer Загальна кількість записів до видалення: {total_records}")
            logger.info(f"Offer Видалено записів: {records_to_delete}")
            logger.info(f"Offer Залишилось записів: {remaining_records}")

            return {
                'total_before': total_records,
                'deleted': records_to_delete,
                'remaining': remaining_records
            }

    except Exception as e:
        logg.error(f"Помилка при видаленні записів: {str(e)}")
        raise


if __name__ == "__main__":
    try:
        logg.info("Запуск процесу видалення застарілих записів з RawOffers")
        result = cleanup_old_records_raw()
        logg.info(f"Процес Raw успішно завершено. Видалено {result['deleted']} з {result['total_before']} записів.")

        result_offer = cleanup_old_records_offer()
        logg.info(f"Процес Offer успішно завершено. Видалено {result_offer['deleted']} з {result_offer['total_before']} записів.")
    except Exception as e:
        logg.error(f"Критична помилка при виконанні скрипта: {str(e)}")
        sys.exit(1)
