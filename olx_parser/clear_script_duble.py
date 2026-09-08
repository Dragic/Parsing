from sqlalchemy import text
from database import DBSession

BATCH_SIZE = 100_000


def delete_duplicate_offers():
    session = DBSession()
    try:
        while True:
            try:
                # Пошук дублів по ad_id і source = 'olx'
                query = text(f"""
                    DELETE o1
                    FROM offer_logs o1
                    JOIN (
                        SELECT o1.id
                        FROM offer_logs o1
                        JOIN offer_logs o2
                          ON o1.offer_id = o2.offer_id
                         AND o1.id < o2.id
                         WHERE o1.change_type = 'created'; 
                        LIMIT {BATCH_SIZE}
                    ) dup ON o1.id = dup.id;
                """)
                result = session.execute(query)
                session.commit()

                # Якщо більше немає що видаляти — вихід
                if result.rowcount == 0:
                    print("✅ No more duplicates to delete.")
                    break

                print(f"🧹 Deleted {result.rowcount} duplicate rows...")
            except Exception as ex:
                print(ex)
                session.rollback()
    finally:
        session.close()


if __name__ == '__main__':
    delete_duplicate_offers()
