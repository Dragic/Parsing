from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager
from settings import settings


engine = create_engine(
    settings.DATABASE_URL, connect_args={**settings.DATABASE_CONNECT_DICT}
)

Base = declarative_base()

DBSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
session = DBSession()


@contextmanager
def db_session():
    session_con = DBSession()
    session_con.expire_on_commit = False
    try:
        yield session_con
    except BaseException:
        session_con.rollback()
        raise
    finally:
        session_con.close()
