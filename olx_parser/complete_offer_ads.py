import sys
import time
from datetime import datetime
from sqlalchemy import func
from database import db_session
import models
import logging

logg = logging.getLogger('log.complete_offer_ads.py')


def copy_not_realtor_to_offers(source, batch_size=50, max_ads_per_author=2):
    """
    Копіює оголошення з RawOffers в Offers для авторів,
    які мають не більше max_ads_per_author оголошень
    """
    start_time = time.time()
    total_processed = 0
    total_copied = 0
    total_skipped = 0

    try:
        with db_session() as session:

            # Отримуємо кількість оголошень для кожного автора з OLX
            author_counts = session.query(
                models.RawOffer.author_id,
                func.count(models.RawOffer.id).label('ads_count')
            ).filter(
                models.RawOffer.source == source,
                models.RawOffer.author_id.isnot(None)
            ).group_by(
                models.RawOffer.author_id
            ).all()

            logg.info(f"Знайдено {len(author_counts)} авторів з платформи OLX")

            # Відбираємо авторів з не більше ніж max_ads_per_author оголошеннями
            eligible_authors = [author_id for author_id, ads_count in author_counts if ads_count <= max_ads_per_author]
            logg.info(f"З них {len(eligible_authors)} авторів мають не більше {max_ads_per_author} оголошень")

            # Отримуємо всі оголошення для підходящих авторів
            raw_offers = session.query(models.RawOffer).filter(
                models.RawOffer.source == source,
                models.RawOffer.owner_type == 'private',
                models.RawOffer.author_id.in_(eligible_authors)
            ).all()

            logg.info(f"Загальна кількість оголошень для обробки: {len(raw_offers)}")

            # Обробляємо оголошення батчами
            for i, raw_offer in enumerate(raw_offers, 1):
                print(f'Get: {i} - {raw_offer}')
                total_processed += 1

                # Перевіряємо, чи є вже таке оголошення в Offers
                existing_offer = session.query(models.Offer).filter(
                    models.Offer.ad_id == raw_offer.ad_id,
                    models.Offer.source == raw_offer.source
                ).first()

                if existing_offer:
                    total_skipped += 1
                    continue

                # Створюємо новий запис в Offers
                new_offer = models.Offer(
                    ad_id=raw_offer.ad_id,
                    title=raw_offer.title,
                    source=raw_offer.source,
                    price=raw_offer.price,
                    currency=raw_offer.currency,
                    type=raw_offer.type,
                    action=raw_offer.action,
                    residential_complex=raw_offer.residential_complex,
                    city_id=raw_offer.city_id,
                    district_id=raw_offer.district_id,
                    region_id=raw_offer.region_id,
                    street=raw_offer.street,
                    house_number=raw_offer.house_number,
                    floors=raw_offer.floors,
                    floor=raw_offer.floor,
                    total_area=raw_offer.total_area,
                    rooms=raw_offer.rooms,
                    map_position=raw_offer.map_position,
                    landmark=raw_offer.landmark,
                    ad_link=raw_offer.ad_link,
                    description=raw_offer.description,
                    main_photo=raw_offer.main_photo,
                    photos=raw_offer.photos,
                    market_type=raw_offer.market_type,
                    author_id=raw_offer.author_id,
                    author_link=raw_offer.author_link,
                    e_oselya=raw_offer.e_oselya,
                    owner_type=raw_offer.owner_type,
                    refresh_time=raw_offer.refresh_time,
                    irrelevance=raw_offer.irrelevance,
                    irrelevant_users=raw_offer.irrelevant_users,
                    created_at=raw_offer.created_at,
                    updated_at=datetime.now()
                )

                session.add(new_offer)
                total_copied += 1

                if i % 100 == 0:
                    logg.debug(f"Скопійовано оголошення: ID={raw_offer.ad_id}, Source={raw_offer.source}")

                # Комітимо зміни батчами
                if i % batch_size == 0:
                    session.commit()
                    logg.info(f"Оброблено {i} з {len(raw_offers)} оголошень")

            # Комітимо залишок змін
            if total_processed % batch_size != 0:
                session.commit()

            logg.info(f"Всього оброблено {total_processed} оголошень")
            logg.info(f"Скопійовано {total_copied} нових оголошень")
            logg.info(f"Пропущено {total_skipped} дублікатів")

    except Exception as e:
        logg.error(f"Помилка при копіюванні оголошень: {str(e)}")
        raise

    execution_time = time.time() - start_time
    logg.info(f"Скрипт виконано за {execution_time:.2f} секунд")
    return {
        'total_processed': total_processed,
        'total_copied': total_copied,
        'total_skipped': total_skipped,
        'execution_time': execution_time
    }


if __name__ == "__main__":
    try:
        logg.info("Початок копіювання оголошень від не-ріелторів")

        source_list = ['OLX', 'DOMRIA']
        for source in source_list:
            batch_size = 500
            max_ads_per_author = 2

            result = copy_not_realtor_to_offers(source=source,
                                                batch_size=batch_size,
                                                max_ads_per_author=max_ads_per_author)
            logg.info(f"{source} Результат: скопійовано {result['total_copied']} з {result['total_processed']} оголошень")

    except Exception as e:
        logg.error(f"Критична помилка при виконанні скрипта: {str(e)}")
        sys.exit(1)
