from sqlalchemy import func, desc, and_
from database import db_session
from models import Offer


def remove_duplicate_offers():
    print("Починаю пошук та видалення дублікатів оголошень...")

    # Статистика до операції
    with db_session() as session:
        total_offers = session.query(func.count(Offer.id)).scalar()
        print(f"Загальна кількість оголошень до видалення дублікатів: {total_offers}")

    # Крок 1: Знайти дублікати на основі source та ad_id
    with db_session() as session:
        # Отримуємо групи з однаковими source та ad_id, та кількість записів у кожній групі
        duplicates = session.query(
            Offer.source,
            Offer.ad_id,
            func.count(Offer.id).label('count')
        ).group_by(
            Offer.source,
            Offer.ad_id
        ).having(
            func.count(Offer.id) > 1
        ).all()

        print(f"Знайдено {len(duplicates)} груп дублікатів")

        # Якщо дублікатів не знайдено, завершуємо
        if not duplicates:
            print("Дублікатів не знайдено. Робота завершена.")
            return

        # Статистика про кількість дублікатів
        total_duplicates = sum([dup.count - 1 for dup in duplicates])
        print(f"Загальна кількість дублікатів (зайвих записів): {total_duplicates}")

    # Крок 2: Для кожної групи дублікатів залишаємо тільки один запис (найновіший)
    duplicates_removed = 0

    for dup in duplicates:
        source_value = dup.source
        ad_id_value = dup.ad_id

        with db_session() as session:
            # Отримуємо всі записи з однаковими source та ad_id, сортуємо за датою оновлення
            duplicate_records = session.query(Offer).filter(
                and_(
                    Offer.source == source_value,
                    Offer.ad_id == ad_id_value
                )
            ).order_by(desc(Offer.updated_at)).all()

            # Залишаємо перший (найновіший) запис, видаляємо решту
            records_to_keep = duplicate_records[0]
            records_to_delete = duplicate_records[1:]

            # Виводимо інформацію про групу дублікатів
            print(f"Група: {source_value} - {ad_id_value}, знайдено {len(duplicate_records)} записів")
            print(f"  Збережено: ID {records_to_keep.id}, оновлено: {records_to_keep.updated_at}")

            # Видаляємо дублікати
            for record in records_to_delete:
                print(f"  Видалено: ID {record.id}, оновлено: {record.updated_at}")
                session.delete(record)
                duplicates_removed += 1

            session.commit()

    # Статистика після операції
    with db_session() as session:
        remaining_offers = session.query(func.count(Offer.id)).scalar()
        print(f"\nОперація завершена!")
        print(f"Видалено дублікатів: {duplicates_removed}")
        print(f"Залишилось оголошень: {remaining_offers}")
        print(f"Відсоток скорочення: {(duplicates_removed / total_offers * 100):.2f}%")

    # Перевірка на наявність залишкових дублікатів
    with db_session() as session:
        remaining_duplicates = session.query(
            Offer.source,
            Offer.ad_id,
            func.count(Offer.id).label('count')
        ).group_by(
            Offer.source,
            Offer.ad_id
        ).having(
            func.count(Offer.id) > 1
        ).all()

        if remaining_duplicates:
            print(f"УВАГА: Після очищення все ще залишилось {len(remaining_duplicates)} груп дублікатів!")
            print("Можлива проблема з транзакціями. Рекомендується запустити скрипт ще раз.")
        else:
            print("Перевірка: дублікатів не знайдено. Операція успішна!")


if __name__ == "__main__":
    remove_duplicate_offers()
    