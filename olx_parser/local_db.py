from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager


Base = declarative_base()

engine = create_engine('sqlite:///local_db.sqlite3', echo=False)
metadata = Base.metadata
DBSession = sessionmaker(bind=engine)
session = DBSession()


@contextmanager
def db_session():
    session.expire_on_commit = False
    try:
        yield session
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
