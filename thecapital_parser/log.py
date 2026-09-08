import logging
import os
from logging.handlers import RotatingFileHandler

def setup_logger():
    # Створюємо Logger
    logger = logging.getLogger('log')
    logger.setLevel(logging.DEBUG)

    # Очищаємо попередні хендлери, якщо вони є
    logger.handlers.clear()

    # Шлях до директорії з логами
    log_dir = 'logs'
    os.makedirs(log_dir, exist_ok=True)

    # Налаштування RotatingFileHandler
    # Максимальний розмір файлу - 5 МБ
    # Максимальна кількість файлів - 5
    handler = RotatingFileHandler(
        filename=os.path.join(log_dir, 'app.log'),
        maxBytes=5 * 1024 * 1024,  # 5 МБ
        backupCount=5,  # 5 файлів історії
        encoding='utf-8'
    )

    # Форматування логів
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)

    # Додаємо хендлер до логера
    logger.addHandler(handler)

    # Додаємо також вивід до консолі (опціонально)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

# Створюємо глобальний логер
logger = setup_logger()