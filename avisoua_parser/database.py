from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager
from settings import settings

engine = create_engine(
    settings.DATABASE_URL, connect_args={
        "connect_timeout": 300,
                                         **settings.DATABASE_CONNECT_DICT}
)

Base = declarative_base()

DBSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
session = DBSession()

def get_db():
    db = DBSession()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session():
    session.expire_on_commit = True
    try:
        yield session
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
