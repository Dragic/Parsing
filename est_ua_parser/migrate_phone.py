from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Offer, Contact, ContactNew
from settings import settings
import logging

logger = logging.getLogger(__name__)

engine = create_engine(settings.DATABASE_URL)
Session = sessionmaker(bind=engine)

BATCH_SIZE = 100


def migrate_offer_contacts(source: str = 'AVISOUA'):
    session = Session()

    try:
        total = session.query(Offer).filter(
            Offer.source == source,
            Offer.contact_new_id.is_(None),
            Offer.contact_id.isnot(None)
        ).count()

        logger.info(f"Всього офферів для міграції [{source}]: {total}")

        updated = 0
        not_found = 0
        offset = 0

        while offset < total:
            batch = session.query(Offer).filter(
                Offer.source == source,
                Offer.contact_new_id.is_(None),
                Offer.contact_id.isnot(None)
            ).order_by(Offer.id).offset(offset).limit(BATCH_SIZE).all()

            if not batch:
                break

            # Збираємо всі contact_id з батчу
            contact_ids = [o.contact_id for o in batch]

            # Отримуємо старі контакти з телефонами
            old_contacts = session.query(Contact).filter(
                Contact.id.in_(contact_ids),
                Contact.phone.isnot(None),
                Contact.phone != ''
            ).all()

            # Словник contact_id → phone
            contact_phone_map = {c.id: c.phone.strip() for c in old_contacts}

            # Отримуємо нові контакти по телефонах
            phones = list(contact_phone_map.values())
            new_contacts = session.query(ContactNew).filter(
                ContactNew.phone.in_(phones)
            ).all()

            # Словник phone → contact_new_id
            phone_new_contact_map = {c.phone: c.id for c in new_contacts}

            # Оновлюємо оффери
            for offer in batch:
                phone = contact_phone_map.get(offer.contact_id)
                if not phone:
                    not_found += 1
                    continue

                new_contact_id = phone_new_contact_map.get(phone)
                if new_contact_id:
                    offer.contact_new_id = new_contact_id
                    updated += 1
                else:
                    not_found += 1
                    logger.warning(f"Не знайдено contact_new для phone={phone} offer_id={offer.id}")

            session.commit()
            offset += BATCH_SIZE
            logger.info(f"Оброблено {min(offset, total)}/{total} | оновлено: {updated} | не знайдено: {not_found}")

        logger.info(f"✅ Готово! Оновлено: {updated} | Не знайдено: {not_found}")

    except Exception as e:
        session.rollback()
        logger.error(f"❌ Помилка: {e}")
        raise
    finally:
        session.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    migrate_offer_contacts(source='AVISOUA')