from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from settings import settings
import logging
from logging.handlers import RotatingFileHandler
import os
from datetime import datetime
from sqlalchemy import event
from sqlalchemy.engine import Engine
import time
from contextlib import contextmanager


if 'sqlite' in settings.DATABASE_URL:
    engine = create_engine(
        settings.DATABASE_URL, connect_args={
            **settings.DATABASE_CONNECT_DICT}
    )

else:
    engine = create_engine(
        settings.DATABASE_URL, connect_args={
            "connect_timeout": 300,
            **settings.DATABASE_CONNECT_DICT}
    )


Base = declarative_base()

DBSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
session = DBSession()


class DatabaseQueryLogger:
    def __init__(self, log_dir='logs'):
        # Створення директорії для логів, якщо вона не існує
        os.makedirs(log_dir, exist_ok=True)

        # Налаштування логера
        self.logger = logging.getLogger('db_query_logger')
        self.logger.setLevel(logging.INFO)

        # Formatter для логів
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # Файловий хендлер з ротацією
        log_file = os.path.join(log_dir, f'db_queries_{datetime.now().strftime("%Y%m%d")}.log')
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5
        )
        file_handler.setFormatter(formatter)

        # Консольний хендлер
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)

        # Додавання хендлерів
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

        # Змінні для трекінгу
        self.reset()

    def reset(self):
        """Скидання лічильників"""
        self.total_queries = 0
        self.queries = []
        self.start_time = time.time()

    @contextmanager
    def track_queries(self):
        """Контекстний менеджер для трекінгу запитів"""
        # Скидаємо попередню статистику
        self.reset()

        # Функція для трекінгу запитів
        def query_tracker(conn, cursor, statement, parameters, context, executemany):
            self.total_queries += 1
            query_info = {
                'number': self.total_queries,
                'statement': statement.strip(),
                'parameters': parameters
            }
            self.queries.append(query_info)

        # Реєстрація трекера
        event.listen(Engine, 'before_cursor_execute', query_tracker)

        try:
            yield
        finally:
            # Зняття трекера
            event.remove(Engine, 'before_cursor_execute', query_tracker)

            # Логування статистики
            total_time = time.time() - self.start_time
            self.logger.info(f"Total queries executed: {self.total_queries}")
            self.logger.info(f"Total query execution time: {total_time:.4f} sec")

            # Детальний лог запитів (за бажанням)
            if self.total_queries > 0:
                self.logger.info("Query details:")
                for query in self.queries:
                    self.logger.info(
                        f"Query #{query['number']}: {query['statement'][:200]}..."
                    )

    def log_slow_queries(self, threshold=0.1):
        """Логування повільних запитів"""
        slow_queries = [
            q for q in self.queries
            if q.get('execution_time', 0) > threshold
        ]

        if slow_queries:
            self.logger.warning(f"Detected {len(slow_queries)} slow queries:")
            for query in slow_queries:
                self.logger.warning(
                    f"Slow query: {query['statement'][:100]}... "
                    f"(Execution time: {query['execution_time']:.4f} sec)"
                )


# Створення глобального логера
db_query_logger = DatabaseQueryLogger()


@contextmanager
def db_session():
    session_con = DBSession()
    session_con.expire_on_commit = False

    try:
        if settings.TEST:
            # Використання трекінгу запитів
            with db_query_logger.track_queries():
                yield session_con
        else:
            yield session_con
    except BaseException:
        session_con.rollback()
        db_query_logger.logger.exception("Database session error")
        raise
    finally:
        session_con.close()
