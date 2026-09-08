from sqlalchemy import text
from database import DBSession

BATCH_SIZE = 100_000

# Keeps the newest `created` log per offer and deletes the older ones, in
# batches so a single statement never locks the whole table.
#
# PostgreSQL has no MySQL multi-table `DELETE t1 FROM t1 JOIN t2` form, so the
# rows to drop are selected in a subquery and removed with `DELETE ... USING`.
# The self-join is constrained to a single change_type on BOTH sides: joining a
# `created` row against a row of any other type would match every offer that has
# a `created` log plus any later log, and delete the `created` one.
DELETE_DUPLICATE_LOGS = text("""
    DELETE FROM offer_logs
    USING (
        SELECT DISTINCT o1.id
        FROM offer_logs o1
        JOIN offer_logs o2
          ON o1.offer_id = o2.offer_id
         AND o1.change_type = o2.change_type
         AND o1.id < o2.id
        WHERE o1.change_type = 'created'
        LIMIT :batch_size
    ) dup
    WHERE offer_logs.id = dup.id
""")


def delete_duplicate_offer_logs(batch_size: int = BATCH_SIZE):
    session = DBSession()
    try:
        while True:
            try:
                result = session.execute(DELETE_DUPLICATE_LOGS, {"batch_size": batch_size})
                session.commit()
            except Exception as ex:
                # Retrying the same failing statement would spin forever.
                session.rollback()
                print(f"Aborted: {ex}")
                break

            if result.rowcount == 0:
                print("No more duplicates to delete.")
                break

            print(f"Deleted {result.rowcount} duplicate rows...")
    finally:
        session.close()


if __name__ == '__main__':
    delete_duplicate_offer_logs()
