import sys
import time
import logging
from datetime import datetime
from sqlalchemy import text
from database import db_session
import models
from log import logger

logg = logging.getLogger('log.is_realtor_script.py')


def execute_raw_sql(sql_query):
    """
    Выполняет сырой SQL-запрос

    Args:
        sql_query (str): SQL-запрос для выполнения

    Returns:
        dict: Результаты выполнения запроса
    """
    start_time = time.time()

    try:
        with db_session() as session:
            result = session.execute(text(sql_query))
            session.commit()
            rowcount = result.rowcount

        execution_time = time.time() - start_time
        return {
            'rows_updated': rowcount,
            'execution_time': execution_time
        }
    except Exception as e:
        logg.error(f"Ошибка при выполнении SQL-запроса: {str(e)}")
        raise


if __name__ == "__main__":
    try:
        logg.info("Початок оновлення статусу ріелторів")

        # SQL-запрос для OLX - условие изменено на > 2 (больше 2)
        olx_sql = """
        UPDATE offers 
        SET is_realtor = 1, 
            updated_at = NOW() 
        WHERE author_id IN (
            SELECT author_id FROM (
                SELECT author_id 
                FROM offers 
                WHERE source = 'OLX' 
                AND author_id IS NOT NULL 
                GROUP BY author_id 
                HAVING COUNT(*) > 2
            ) AS realtor_authors
        ) 
        AND source = 'OLX' 
        AND is_realtor != 1;
        """

        # Выполняем запрос для OLX
        olx_result = execute_raw_sql(olx_sql)
        logg.info(
            f"OLX результат: оновлено {olx_result['rows_updated']} оголошень. Час виконання: {olx_result['execution_time']:.2f} сек.")

        # SQL-запрос для DOMRIA - условие изменено на > 2 (больше 2)
        domria_sql = """
        UPDATE offers 
        SET is_realtor = 1, 
            updated_at = NOW() 
        WHERE author_id IN (
            SELECT author_id FROM (
                SELECT author_id 
                FROM offers 
                WHERE source = 'DOMRIA' 
                AND author_id IS NOT NULL 
                GROUP BY author_id 
                HAVING COUNT(*) > 2
            ) AS realtor_authors
        ) 
        AND source = 'DOMRIA' 
        AND is_realtor != 1;
        """

        # Выполняем запрос для DOMRIA
        domria_result = execute_raw_sql(domria_sql)
        logg.info(
            f"DOMRIA результат: оновлено {domria_result['rows_updated']} оголошень. Час виконання: {domria_result['execution_time']:.2f} сек.")

        # Общие результаты
        total_updated = olx_result['rows_updated'] + domria_result['rows_updated']
        total_time = olx_result['execution_time'] + domria_result['execution_time']
        logg.info(f"Загальний результат: оновлено {total_updated} оголошень. Загальний час: {total_time:.2f} сек.")

    except Exception as e:
        logg.error(f"Критична помилка при виконанні скрипта: {str(e)}")
        sys.exit(1)