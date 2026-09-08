import datetime

from sqlalchemy import Column, Integer, String, Boolean, DateTime
from local_db import Base, engine, db_session


class Ads(Base):
    __tablename__ = "ads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ads_id = Column(String(200), nullable=True, default=None)
    url = Column(String(300), nullable=True, default=None)
    city_id = Column(Integer, nullable=True, default=None)
    create_at = Column(DateTime, default=datetime.datetime.utcnow)

    @classmethod
    def create_ads(cls, ads_id: str, url: str, city_id: int) -> bool:
        with db_session() as session:
            exist = session.query(cls).filter(cls.ads_id == ads_id).first()
            if exist:
                return False

            create_user = cls(
                ads_id=ads_id,
                url=url,
                city_id=city_id,
            )
            session.add(create_user)
            session.commit()
            return True


Base.metadata.create_all(engine)
