import logging


def setup_logger():
    logger = logging.getLogger('log')
    logger.setLevel(logging.DEBUG)

    file_handler = logging.FileHandler('logs.log')
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)

    return logger


logger = setup_logger()
