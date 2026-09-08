from collections import defaultdict

from database import Base, engine, db_session

from sqlalchemy import (
    Integer, BigInteger, JSON, DateTime,
    ForeignKey, Numeric, Boolean, Float, Column,
    String, Text, TIMESTAMP, Index, Enum as SAEnum, UniqueConstraint
)
from sqlalchemy.orm import relationship, joinedload
from sqlalchemy.sql import func
from datetime import datetime, timedelta
from settings import settings


class Country(Base):
    __tablename__ = 'countries'

    id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    name = Column(String(255), nullable=False)
    code = Column(String(255), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)

    regions = relationship("Region", back_populates="country", cascade="all, delete-orphan")


class Region(Base):
    __tablename__ = 'regions'

    id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    olx_id = Column(Integer, nullable=True)
    name = Column(String(255), nullable=False)
    country_id = Column(BigInteger, ForeignKey('countries.id', onupdate="RESTRICT", ondelete="CASCADE"), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    parsing = Column(Boolean, nullable=False, default=False)

    country = relationship("Country", back_populates="regions")
    cities = relationship("City", back_populates="region", cascade="all, delete-orphan")

    @classmethod
    def get_all_cities_from_parsing_regions_domria(cls, country_id) -> dict:
        response = {}
        with db_session() as session:
            # Отримання регіонів з містами
            regions_query = (
                session.query(Region)
                .filter(Region.parsing == True, Region.country_id == country_id)
                .options(joinedload(Region.cities))
                .all()
            )

            # Отримання всіх районів одним запитом
            all_districts = session.query(District).all()
            # districts_by_city = defaultdict(list)
            districts_by_city = defaultdict(dict)
            for district in all_districts:
                # districts_by_city[district.city_id].append(district.id)
                districts_by_city[district.city_id][district.id] = district.parent_id

            # Формування структурованої відповіді
            for region in regions_query:
                region_cities = {}

                for city in region.cities:
                    if city.parsing == True:
                        region_cities[city.id] = {
                            'city_id': city.id,
                            'city_name': city.name,
                            'olx_id': city.olx_id,
                            'ai_processed': city.ai_processed,
                            'detect_photo_duplicates': city.detect_photo_duplicates,
                            'districts': districts_by_city.get(city.id, [])
                        }

                # Додаємо лише регіони з містами
                if region_cities:
                    response[region.id] = {
                        'region_id': region.id,
                        'region_name': region.name,
                        'cities': region_cities
                    }

        return response

    @classmethod
    def get_all_cities_from_parsing_regions(cls, country_id) -> dict:
        response = {}
        region_dict = {}
        with db_session() as session:
            regions = session.query(cls).filter(cls.parsing == True, cls.country_id == country_id).all()

            for region in regions:
                cities = [city for city in region.cities if city.parsing == True]
                city_olx_list = []
                for city in cities:
                    if city.olx_id is None:
                        continue

                    if city.parsing == False:
                        continue

                    city_olx_list.append(city.olx_id)

                    districts = []
                    for district in city.districts:
                        districts.append({
                            'id': district.id,
                            'name': district.name,
                            'olx_id': district.olx_id
                        })

                    response[city.olx_id] = {
                        'region_id': region.id,
                        'region_olx_id': region.olx_id,
                        'city_id': city.id,
                        'city_name': city.name,
                        'ai_processed': city.ai_processed,
                        'detect_photo_duplicates': city.detect_photo_duplicates,
                        'olx_id': city.olx_id,
                        'districts': districts,
                    }
                region_dict[region.olx_id] = {'region_olx_id': region.olx_id,
                                              'region_id': region.id,
                                              'city': response,
                                              'city_olx_ids': city_olx_list}
        return region_dict


class City(Base):
    __tablename__ = 'cities'

    id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    olx_id = Column(Integer, nullable=True)
    name = Column(String(255), nullable=False)
    region_id = Column(BigInteger, ForeignKey('regions.id', onupdate="RESTRICT", ondelete="CASCADE"), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    parsing = Column(Boolean, nullable=False, default=True)
    detect_photo_duplicates = Column(Boolean, nullable=False, default=False)
    ai_processed = Column(Boolean, nullable=False, default=False)

    region = relationship("Region", back_populates="cities")
    districts = relationship("District", back_populates="city", cascade="all, delete-orphan")

    @classmethod
    def get_region_city_settings(cls, region_id) -> dict:
        response = {}
        with db_session() as session:
            rows = session.query(cls).filter(cls.parsing == True, cls.region_id == region_id).all()
            for row in rows:
                response[row.id] = {'detect_photo_duplicates': row.detect_photo_duplicates,
                                    'ai_processed': row.ai_processed}
        return response

    @classmethod
    def get_districts_by_region_grouped(cls, region_id: int):
        """
        Отримання districts, де ключ - місто, а значення - словник districts
        Включає всі міста регіону, навіть без районів
        """
        with db_session() as session:
            # Спочатку отримуємо всі міста регіону
            cities = (
                session.query(City)
                .filter(City.region_id == region_id)
                .order_by(City.name)
                .all()
            )

            # Отримуємо райони для міст регіону
            districts_query = (
                session.query(City, District)
                .join(District, isouter=True)
                .filter(City.region_id == region_id)
                .order_by(City.name, District.sort_order)
                .all()
            )

            # Структурування результату
            result = {}
            for city in cities:
                # Додаємо місто навіть без районів
                result[city.name] = {'id': city.id}

            # Додаємо райони до відповідних міст
            for city, district in districts_query:
                if district:
                    result[city.name][district.name] = {
                        'id': district.id
                    }

            return result

    @classmethod
    def get_cities_by_region(cls, region_id) -> dict:
        response = {}
        with db_session() as session:
            rows = session.query(cls).filter(cls.parsing == True, cls.region_id == region_id).all()
            for row in rows:
                response[row.name] = row.id
        return response

    @classmethod
    def get_cities(cls) -> list:
        response = []
        with db_session() as session:
            rows = session.query(cls).filter(cls.parsing == True).all()
            for row in rows:
                response.append(f'olx_id: {row.olx_id}')
        return response

    @classmethod
    def get_city(cls, city_id) -> int | None:
        with db_session() as session:
            row = session.query(cls).filter(cls.id == city_id).first()
            if row:
                return row.olx_id
        return None

    @classmethod
    def get_olx_city(cls, city_id) -> dict:
        with db_session() as session:
            row = session.query(cls).filter(cls.olx_id == city_id).first()
            if row:
                return {'city_id': row.id, 'region_id': row.region_id}
        return {}


class District(Base):
    __tablename__ = 'districts'

    id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    olx_id = Column(Integer, nullable=True)
    name = Column(String(255), nullable=False)
    city_id = Column(BigInteger, ForeignKey('cities.id', onupdate="RESTRICT", ondelete="CASCADE"), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    parsing = Column(Boolean, nullable=False, default=True)
    parent_id = Column(Integer, nullable=True)

    city = relationship("City", back_populates="districts")

    @classmethod
    def get_olx_district(cls, olx_id: int):
        with db_session() as session:
            obj = session.query(cls).filter(cls.olx_id == olx_id, cls.parsing == True).first()
            if obj:
                return obj.id
            return None


class Offer(Base):
    __tablename__ = 'offers'

    id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    ad_id = Column(BigInteger, nullable=False, default=0)
    title = Column(String(255), nullable=True)
    source = Column(
        SAEnum('OLX', 'DOMRIA', 'RIELTORUA', 'DOMIKUA', '100REALTYUA', 'AVISOUA', 'OBYAVAUA', 'M2BOMBER', 'ESTUA',
               'LUNUA', 'VALIONUA', 'THECAPITAL', 'PrivatBase',
               name='platform_enum'),
        nullable=False
    )
    price = Column(Integer, nullable=True)
    currency = Column(String(3), nullable=False)
    type = Column(
        SAEnum('apartment', 'house', 'commercial', 'land', 'garage', 'room', name='re_type_enum'),
        nullable=False
    )
    action = Column(
        SAEnum('sale', 'rent', name='action_enum'),
        nullable=False
    )
    residential_complex = Column(String(255), nullable=True)
    city_id = Column(Integer, nullable=True)
    district_id = Column(Integer, nullable=True)
    region_id = Column(Integer, nullable=True)
    microdistrict_id = Column(Integer, nullable=True)
    housing_complex_id = Column(BigInteger, nullable=True)
    has_phone = Column(Boolean, default=True)
    street = Column(String(255), nullable=True)
    house_number = Column(String(50), nullable=True)
    floors = Column(Integer, nullable=True)
    floor = Column(Integer, nullable=True)
    total_area = Column(Numeric(10, 2), nullable=True)

    latitude = Column(Numeric(20, 15), nullable=True)
    longitude = Column(Numeric(20, 15), nullable=True)

    rooms = Column(Integer, nullable=True)
    landmark = Column(String(255), nullable=True)
    ad_link = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, default=func.now(), nullable=True)
    updated_at = Column(TIMESTAMP, default=func.now(), onupdate=func.now(), nullable=True)
    main_photo = Column(String(255), nullable=True)
    photos = Column(
        JSON(none_as_null=True),
        nullable=True
    )

    subway_id = Column(BigInteger, nullable=True)

    is_realtor = Column(Boolean, nullable=False, default=False)
    market_type = Column(SAEnum('primary', 'secondary', name='market_type_enum'), nullable=True)
    e_oselya = Column(Boolean, nullable=True)
    is_e_vidnovlennia = Column(Boolean, default=False)
    owner_type = Column(SAEnum('business', 'private', name='owner_type_enum'), nullable=True)
    refresh_time = Column(DateTime, default=func.now(), nullable=True)
    group_id = Column(Integer, nullable=True)
    from_developer = Column(Boolean, default=False)
    call_status = Column(String(255), nullable=True)

    is_top = Column(Boolean, nullable=True, default=False)

    note = Column(Text, nullable=True)
    note_at = Column(TIMESTAMP, default=None, nullable=True)

    deleted_at = Column(DateTime, nullable=True, default=None)

    kitchen_area = Column(Numeric(10, 2), nullable=True)
    living_area = Column(Numeric(10, 2), nullable=True)
    ai_owner_probability = Column(Numeric(10, 2), nullable=True)
    cadastral_number = Column(String(255), nullable=True)
    has_similars = Column(Boolean, nullable=False, default=0)

    year_construction = Column(Integer, nullable=True)

    no_commission = Column(Boolean, nullable=True)
    street_coordinates = Column(
        JSON(none_as_null=True),
        nullable=True
    )
    is_exchange = Column(Boolean, nullable=True)
    cooperate = Column(Boolean, nullable=True)
    is_furnished = Column(Boolean, nullable=True)

    office_type = Column(
        SAEnum(
            'open_space', 'cabinet_type', 'closed_type', 'open_type', 'with_common_areas', 'other',
            name='office_type_enum'
        ),
        nullable=True
    )

    office_class = Column(
        SAEnum(
            'category_a', 'category_b', 'category_c', 'other',
            name='office_class_enum'
        ),
        nullable=True
    )

    property_type_houses = Column(
        SAEnum('house', 'club_house', 'cottage', 'house_part', 'townhouse', 'country_house', 'duplex', 'modular_homes',
               name='property_type_houses_enum'),
        nullable=True
    )
    property_type_land = Column(
        SAEnum('1', '2', '3', '4', '5', '6', '7', '8', name='property_type_land_enum'),
        nullable=True
    )
    communications = Column(
        JSON(none_as_null=True),
        nullable=True
    )
    repair = Column(
        SAEnum('1', '2', '3', '4', '5', '6', '7', name='repair_enum'),
        nullable=True
    )
    comm_re_type = Column(
        SAEnum('business_center', 'trade_and_office_building', 'administrative_building',
               'non_residential_item_in_residential_building', 'residential_building', 'other',
               name='comm_re_type_enum'),
        nullable=True
    )
    property_type_appartments_sale = Column(
        SAEnum('1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12',
               name='property_type_apartments_sale_enum'),
        nullable=True
    )
    layout = Column(
        SAEnum('separate', 'adjacent_through', 'studio', 'penthouse', 'multilevel',
               'small_family', 'smart', 'two_sided', 'free_layout', name='layout_offers_enum'),
        nullable=True
    )
    bathroom = Column(
        SAEnum('1', '2', '3', '4', name='bathroom_numeric_enum'),
        nullable=True
    )
    heating = Column(
        SAEnum('centralized', 'own_boiler-house', 'individual_gas', 'individual_electro',
               'solid_fuel', 'heat_pump', 'combined', 'other', name='heating_offers_enum'),
        nullable=True
    )
    garage_type = Column(
        SAEnum('metal', 'brick', 'penoblock', 'concrete', name='garage_type_enum'),
        nullable=True
    )
    property_type_parking = Column(
        SAEnum('garage', 'parking_place', 'parking_space', 'technical_room', name='property_type_parking_enum'),
        nullable=True
    )

    appliances = Column(
        JSON(none_as_null=True),
        nullable=True
    )
    multimedia = Column(
        JSON(none_as_null=True),
        nullable=True
    )
    comfort = Column(
        JSON(none_as_null=True),
        nullable=True
    )
    infrastructure_500_m = Column(
        JSON(none_as_null=True),
        nullable=True
    )
    ecosystem_1_km = Column(
        JSON(none_as_null=True),
        nullable=True
    )
    blackout_autonomy = Column(
        JSON(none_as_null=True),
        nullable=True
    )
    land_area = Column(Numeric(10, 2), nullable=True)

    contact_id = Column(BigInteger, ForeignKey('contacts.id', onupdate="RESTRICT", ondelete="SET NULL"), nullable=True)

    contact = relationship("ContactNew", back_populates="offers")
    views = relationship("OfferViews", back_populates="offer", cascade="all, delete-orphan")
    logs = relationship("OfferLog", back_populates="offer", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Offer(id={self.id} ad_id='{self.ad_id}')>"

    @classmethod
    def bulk_create_offers(cls, offers_data: list, source: str = 'OLX'):
        """
        Масове створення оголошень

        :param offers_data: Список словників з даними для створення оголошень
        :param source: Джерело оголошень
        :return: Створені оголошення та статистика з ID
        """
        with db_session() as session:
            # Перевірка на існуючі оголошення
            existing_ad_ids = set(
                session.query(cls.ad_id).filter(
                    cls.ad_id.in_([data.get('ad_id') for data in offers_data]),
                    cls.source == source
                ).all()
            )

            # Фільтрація нових оголошень
            new_offers_data = [
                data for data in offers_data
                if data.get('ad_id') not in existing_ad_ids
            ]

            # Створення об'єктів
            new_offers = []
            uniq_ad_id = []
            for data in new_offers_data:
                if data.get('ad_id') not in uniq_ad_id:
                    # Створення оголошення
                    offer = cls(**data)
                    new_offers.append(offer)
                    uniq_ad_id.append(data.get('ad_id'))

            # Додавання та комміт
            session.add_all(new_offers)
            session.flush()  # Важливо для отримання ID

            # Підготовка результату з ID
            result = {
                'total_offers': len(offers_data),
                'new_offers': len(new_offers),
                'skipped_offers': len(offers_data) - len(new_offers),
                'created_offers': new_offers,
                'created_offer_ids': [offer.id for offer in new_offers],
                'created_ad_ids': {offer.ad_id: offer.id for offer in new_offers}
            }

            session.commit()

            return result

    @classmethod
    def bulk_update_offers(cls, offers_to_update: dict):
        """
        Масове оновлення оголошень

        :param offers_to_update: Словник {ads_id: [список словників з даними для оновлення]}
        """
        with db_session() as session:
            # Отримуємо всі існуючі оголошення за ads_id
            ads_ids = list(offers_to_update.keys())
            existing_offers = session.query(cls).filter(
                cls.ad_id.in_(ads_ids),
                cls.source == 'OLX'
            ).all()

            # Словник для швидкого пошуку
            offers_map = {offer.ad_id: offer for offer in existing_offers}

            # Оновлення кожного оголошення
            for ads_id, update_data_list in offers_to_update.items():
                existing_offer = offers_map.get(ads_id)

                if existing_offer:
                    # Застосовуємо останні дані з списку
                    last_update = update_data_list[-1]

                    for key, value in last_update.items():
                        if value is None and key != 'deleted_at':
                            continue
                        if hasattr(existing_offer, key):
                            setattr(existing_offer, key, value)

                    # Додаткові налаштування при оновленні
                    existing_offer.updated_at = datetime.now()

            # Єдиний комміт для всіх змін
            session.commit()

            return {}

    @classmethod
    def count_authors_offers(cls, author_ids: list, source: str = 'OLX') -> dict:
        """
        Підрахунок кількості оголошень для списку авторів за джерелом

        """
        result = {author_id: 0 for author_id in author_ids}

        with db_session() as session:
            offers_count = session.query(cls.author_id, func.count(cls.id)).filter(
                cls.author_id.in_(author_ids),
                cls.source == source
            ).group_by(cls.author_id).all()

            for author_id, count in offers_count:
                result[author_id] = count

        return result

    @classmethod
    def get_offers_created_at_olx(cls, ad_ids: list, source) -> dict:
        result = {}
        with db_session() as session:
            offers = session.query(cls.id, cls.ad_id, cls.refresh_time, cls.group_id, cls.street).filter(
                cls.ad_id.in_(ad_ids),
                cls.source == source
            ).all()

            for pk, ad_id, refresh_time, group_id, street in offers:
                result[ad_id] = {'created_at': refresh_time, 'group_id': group_id, 'pk': pk, 'street': street}

            # Додаємо ad_id яких немає зі значенням None
            for ad_id in ad_ids:
                if ad_id not in result:
                    result[ad_id] = {}

        return result

    @classmethod
    def get_offers_created_at_full(cls, ad_ids: list, source) -> dict:
        """
        for DOMRIA|
        :param ad_ids:
        :param source:
        :return:
        """
        result = {}
        with db_session() as session:
            offers = session.query(cls.ad_id, cls.created_at).filter(
                cls.ad_id.in_(ad_ids),
                cls.source == source
            ).all()

            for ad_id, created_at in offers:
                result[ad_id] = created_at

            # Додаємо ad_id яких немає зі значенням None
            for ad_id in ad_ids:
                if ad_id not in result:
                    result[ad_id] = None

        return result

    @classmethod
    def get_offers_created_at(cls, ad_ids: list, source) -> dict:
        """
        for parsers
        :param ad_ids:
        :param source:
        :return:
        """
        result = {}
        with db_session() as session:
            offers = session.query(cls.ad_id, cls.created_at).filter(
                cls.ad_id.in_(ad_ids),
                cls.source == source
            ).all()

            for ad_id, created_at in offers:
                result[ad_id] = created_at

        return result

    @classmethod
    def offers_list(cls, period=30, source='OLX') -> list:
        response = []
        with db_session() as session:
            period_date = datetime.now() - timedelta(days=period)
            rows = session.query(cls).filter(cls.source == source,
                                             # cls.region_id == 10,  # ТІЛЬКИ КИЇВСЬКА ОБЛАСТЬ
                                             cls.refresh_time >= period_date,
                                             cls.deleted_at == None).all()
            print(f'Total find for scanning: {len(rows)}')
            for row in rows:
                response.append((row.ad_id, row.id, row.price, row.is_top, row.ad_link, row.currency))
        return response

    @classmethod
    def get_offer(cls, offer_id: int):
        with db_session() as session:
            obj = session.query(cls).filter(cls.id == offer_id, cls.source == 'OLX').first()
            if obj:
                return {'price': obj.price, 'is_top': obj.is_top, 'ad_id': obj.ad_id, 'deleted_at': obj.deleted_at}
            return {}

    @classmethod
    def data(cls, row_id: int | str):
        with db_session() as session:
            obj = session.query(cls).filter(cls.id == row_id).first()
            if not obj:
                return None
            return {
                'id': obj.id,
                'source': obj.source,
                'ad_id': obj.ad_id,
                'type': obj.type,
                'action': obj.action,
                'city_id': obj.city_id,
                'created_at': obj.created_at,
                'updated_at': obj.updated_at,
            }

    @classmethod
    def check_olx_offer(cls, ad_id: int):
        with db_session() as session:
            obj = session.query(cls).filter(cls.ad_id == ad_id, cls.source == 'OLX').first()
            if obj:
                if obj.deleted_at is None:
                    return obj.city_id

            return 0

    @classmethod
    def update(cls, id: int, **kwargs) -> bool:
        with db_session() as session:
            obj = session.query(cls).filter(cls.id == id).first()
            if obj:
                for k, v in kwargs.items():
                    setattr(obj, k, v)
                    session.commit()
                return True
            return False


class OfferViews(Base):
    __tablename__ = 'offer_views'

    id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    offer_id = Column(BigInteger, ForeignKey('offers.id', onupdate="RESTRICT", ondelete="CASCADE"), nullable=False)
    view_count = Column(Integer, nullable=False, default=0)
    view_difference = Column(Integer, nullable=True, default=0)
    is_top = Column(Boolean, nullable=True, default=False)
    created_at = Column(TIMESTAMP, default=func.now(), nullable=True)
    updated_at = Column(TIMESTAMP, default=func.now(), onupdate=func.now(), nullable=True)

    offer = relationship("Offer", back_populates="views")


class OfferLog(Base):
    __tablename__ = 'offer_logs'

    id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    offer_id = Column(BigInteger, ForeignKey('offers.id', onupdate="RESTRICT", ondelete="CASCADE"), nullable=False)
    change_type = Column(
        SAEnum('price_change', 'deleted', 'is_top', 'other', 'created', name='offer_log_change_type_enum'),
        nullable=False
    )
    value = Column(Text, nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, default=func.now(), nullable=False)

    offer = relationship("Offer", back_populates="logs")

    @classmethod
    def log_change(cls, offer_id, change_type, value, details=None):
        """
        Записує зміну оголошення
        """
        with db_session() as session:
            log = cls(
                offer_id=offer_id,
                change_type=change_type,
                value=value,
                details=details
            )
            session.add(log)
            session.flush()

            created_id = log.id

            session.commit()

            return created_id

    @classmethod
    def batch_create_logs(cls, log_new_ads: list, change_type: str = 'created', value: str = "1"):

        if not log_new_ads:
            return

        with db_session() as session:
            logs_to_create = [
                cls(
                    offer_id=offer_id,
                    change_type=change_type,
                    value=value
                )
                for offer_id in log_new_ads
            ]

            session.add_all(logs_to_create)
            session.commit()

    @classmethod
    def log_new_ads(cls, offer_id, change_type, value):
        with db_session() as session:
            obj = session.query(cls).filter(cls.offer_id == offer_id, cls.change_type == change_type).first()
            if obj:
                return False
            log = cls(
                offer_id=offer_id,
                change_type=change_type,
                value=value
            )
            session.add(log)
            session.commit()
            return True


# class UserOfferTracking(Base):
#     __tablename__ = 'notifications'
#
#     id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
#     user_id = Column(BigInteger, nullable=False)
#     offer_id = Column(Integer, nullable=False)
#     price_change = Column(Boolean, nullable=False, default=False)
#     deleted = Column(Boolean, nullable=False, default=False)
#     is_top = Column(Boolean, nullable=False, default=False)
#     created_at = Column(TIMESTAMP, default=func.now(), nullable=True)
#     updated_at = Column(TIMESTAMP, default=func.now(), onupdate=func.now(), nullable=True)
#
#     @classmethod
#     def get_all_tracking_records(cls) -> dict:
#         response = {}
#         with db_session() as session:
#             rows = session.query(cls).all()
#
#             for row in rows:
#                 offer_id = row.offer_id
#
#                 if offer_id not in response:
#                     response[offer_id] = set()
#
#                 # Додаємо стани, якщо вони True
#                 if row.deleted:
#                     response[offer_id].add('deleted')
#                 if row.is_top:
#                     response[offer_id].add('is_top')
#                 if row.price_change:
#                     response[offer_id].add('price_change')
#
#             # Перетворюємо set на list у кінцевому результаті
#             for offer_id in response:
#                 try:
#                     response[offer_id] = list(response[offer_id])
#                 except Exception as ex:
#                     print(ex)
#
#         return response


class Keyword(Base):
    __tablename__ = 'keywords'

    id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    advert_id = Column(BigInteger, nullable=False)
    status = Column(
        SAEnum('active', 'disabled', 'archive', 'error', name='keyword_status_enum'),
        nullable=False
    )
    keyword = Column(String(255), nullable=False)
    created_at = Column(TIMESTAMP, default=func.now(), nullable=True)
    updated_at = Column(TIMESTAMP, default=func.now(), onupdate=func.now(), nullable=True)

    def __repr__(self):
        return f"<Keyword(id={self.id}, keyword='{self.keyword}', status='{self.status}')>"

    @classmethod
    def get_active_keywords(cls):
        """Отримати всі активні ключові слова"""
        with db_session() as session:
            resp = []
            rows = session.query(cls).filter(cls.status == 'active').all()
            for row in rows:
                resp.append({'id': row.id, 'advert_id': row.advert_id, 'status': row.status, 'keyword': row.keyword})
        return resp

    @classmethod
    def update_status(cls, keyword_id, new_status):
        """Оновити статус ключового слова"""
        with db_session() as session:
            keyword = session.query(cls).filter(cls.id == keyword_id).first()
            if keyword:
                keyword.status = new_status
                session.commit()
                return True
        return False


class KeywordLog(Base):
    __tablename__ = 'keyword_logs'

    id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    keyword_id = Column(BigInteger, ForeignKey('keywords.id', onupdate="RESTRICT", ondelete="CASCADE"), nullable=False)
    status = Column(
        SAEnum('found', 'not_found', 'error', name='keyword_log_status_enum'),
        nullable=False
    )
    value = Column(Integer, nullable=True)
    created_at = Column(TIMESTAMP, default=func.now(), nullable=False)

    keyword = relationship("Keyword", backref="logs")

    def __repr__(self):
        return f"<KeywordLog(id={self.id}, keyword_id={self.keyword_id}, status='{self.status}', value={self.value})>"

    @classmethod
    def add_log(cls, keyword_id, status, value=None):
        """Додати новий запис логу для ключового слова"""
        with db_session() as session:
            log = cls(
                keyword_id=keyword_id,
                status=status,
                value=value
            )
            session.add(log)
            session.commit()
            return log

    @classmethod
    def get_logs_for_keyword(cls, db_session, keyword_id, limit=10):
        """Отримати останні логи для вказаного ключового слова"""
        return db_session.query(cls).filter(
            cls.keyword_id == keyword_id
        ).order_by(cls.created_at.desc()).limit(limit).all()

    @classmethod
    def get_statistics_by_status(cls, db_session, period_days=7):
        """Отримати статистику логів за статусами за вказаний період"""
        from sqlalchemy import func, and_
        from datetime import datetime, timedelta

        period_start = datetime.now() - timedelta(days=period_days)

        result = db_session.query(
            cls.status,
            func.count(cls.id).label('count')
        ).filter(
            cls.created_at >= period_start
        ).group_by(
            cls.status
        ).all()

        return {status: count for status, count in result}


class ContactNew(Base):
    __tablename__ = 'contacts'

    id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    group_id = Column(BigInteger, nullable=True)
    name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True, unique=True)
    email = Column(String(255), nullable=True)
    avatar = Column(String(500), nullable=True)
    city_id = Column(BigInteger, ForeignKey('cities.id', onupdate="RESTRICT", ondelete="SET NULL"), nullable=True)
    agency_id = Column(BigInteger, nullable=True)
    is_realtor = Column(Boolean, nullable=False, default=False)
    verification_type = Column(
        SAEnum('auto', 'manual', name='verification_type_enum'),
        nullable=True,
        default='auto'
    )
    verified_id = Column(BigInteger, nullable=True)
    note = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, default=func.now(), onupdate=func.now(), nullable=True)
    verified_at = Column(TIMESTAMP, nullable=True)
    note_at = Column(TIMESTAMP, nullable=True)

    platforms = relationship("ContactPlatform", back_populates="contact")
    offers = relationship("Offer", back_populates="contact", foreign_keys="[Offer.contact_id]")


class ContactPlatform(Base):
    __tablename__ = 'contact_platforms'

    id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    contact_id = Column(BigInteger, ForeignKey('contacts.id', ondelete="CASCADE", onupdate="RESTRICT"), nullable=False)
    platform = Column(
        SAEnum('OLX', 'DOMRIA', 'RIELTORUA', 'DOMIKUA', '100REALTYUA', 'AVISOUA', 'OBYAVAUA', 'M2BOMBER', 'ESTUA',
               'LUNUA', 'VALIONUA', 'THECAPITAL', 'PrivatBase',
               name='platform_enum'),
        nullable=False
    )
    user_id = Column(BigInteger, nullable=True)
    name = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    link = Column(String(500), nullable=True)
    created_at = Column(TIMESTAMP, default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, default=func.now(), onupdate=func.now(), nullable=True)

    contact = relationship("ContactNew", back_populates="platforms")


class ResidentialComplex(Base):
    __tablename__ = "builders_housing_complexes"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    title = Column(String(255), nullable=False)
    description_main = Column(Text, nullable=True)
    description_common = Column(Text, nullable=True)

    map_url = Column(Text, nullable=True)
    sales_department_phone = Column(String(255), nullable=True)

    price_m2 = Column(Numeric(15, 2), nullable=True)

    keywords = Column(
        JSON(none_as_null=True),
        nullable=True
    )

    street = Column(String(255), nullable=True)

    link_to_instagram = Column(String(255), nullable=True)
    link_to_youtube = Column(String(255), nullable=True)
    link_to_lun = Column(String(255), nullable=True)
    link_to_dom_ria = Column(String(255), nullable=True)
    link_to_price = Column(String(255), nullable=True)

    web_site = Column(Text, nullable=True)

    photos = Column(
        JSON(none_as_null=True),
        nullable=True
    )
    master_plans = Column(
        JSON(none_as_null=True),
        nullable=True
    )
    videos = Column(
        JSON(none_as_null=True),
        nullable=True
    )

    developer_id = Column(BigInteger, nullable=True)
    city_id = Column(BigInteger, nullable=True)
    district_id = Column(BigInteger, nullable=True)

    dom_ria_id = Column(Integer, nullable=True)


class OfferSimilar(Base):
    __tablename__ = 'offer_similarities'

    id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    group_id = Column(BigInteger, nullable=False)
    similar_group_id = Column(BigInteger, nullable=False)
    threshold = Column(Numeric(5, 4), nullable=False)
    created_at = Column(TIMESTAMP, default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, default=func.now(), onupdate=func.now(), nullable=True)

    __table_args__ = (
        UniqueConstraint('group_id', 'similar_group_id', name='uq_offer_similars_group_similar'),
        Index('idx_offer_similars_group_id', 'group_id'),
        Index('idx_offer_similars_similar_group_id', 'similar_group_id'),
    )

    @classmethod
    def create_similar(cls, offer_id: int, similar_group_id: int, threshold: float) -> bool:
        try:
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            with db_session() as session:

                group_id = offer_id

                if not group_id or not similar_group_id:
                    return False

                    # Перший запис
                existing_1 = session.query(cls).filter(
                    cls.group_id == group_id,
                    cls.similar_group_id == similar_group_id
                ).first()
                if not existing_1:
                    session.add(cls(group_id=group_id, similar_group_id=similar_group_id, threshold=threshold))

                # Зворотній запис
                existing_2 = session.query(cls).filter(
                    cls.group_id == similar_group_id,
                    cls.similar_group_id == group_id
                ).first()
                if not existing_2:
                    session.add(cls(group_id=similar_group_id, similar_group_id=group_id, threshold=threshold))

                session.query(Offer).filter(
                    Offer.group_id == offer_id
                ).update({'has_similars': True}, synchronize_session=False)

                session.commit()
                return True

        except Exception as e:
            print(f"Помилка створення запису: {e}")
            return False

    @classmethod
    def get_similars_by_group(cls, group_id: int) -> list:
        try:
            with db_session() as session:
                records = (
                    session.query(cls)
                    .filter(cls.group_id == group_id)
                    .order_by(cls.threshold.desc())
                    .all()
                )

                return [
                    {
                        'id': r.id,
                        'group_id': r.group_id,
                        'similar_offer_id': r.similar_group_id,
                        'threshold': float(r.threshold),
                        'created_at': r.created_at,
                    }
                    for r in records
                ]

        except Exception as e:
            print(f"Помилка отримання записів: {e}")
            return []


class OfferRequest(Base):
    __tablename__ = 'offer_requests'

    id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    tenant_id = Column(BigInteger, nullable=False)
    user_id = Column(BigInteger, nullable=False)
    offer_id = Column(BigInteger, nullable=True)  # заповнюється API або парсером після створення
    source_url = Column(Text, nullable=True)  # оригінальний URL від користувача
    status = Column(
        SAEnum('pending', 'succeeded', 'failed', name='offer_request_status_enum'),
        nullable=False,
        default='pending',
    )
    processed_at = Column(TIMESTAMP, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(TIMESTAMP, nullable=True)  # зарезервовано, парсер не пише

    __table_args__ = (
        Index(
            'offer_requests_pending_fifo_idx',
            'created_at',
            postgresql_where="status = 'pending' AND deleted_at IS NULL",
        ),
    )

    def __repr__(self):
        return f'<OfferRequest id={self.id} status={self.status}>'

    @classmethod
    def get_pending_batch(cls, limit: int = 100) -> list:
        """
        Повертає пачку pending-запитів у FIFO-порядку.
        Поля: id, tenant_id, user_id, offer_id, source_url.
        FOR UPDATE SKIP LOCKED — захист від подвійної обробки при кількох воркерах.
        """
        with db_session() as session:
            rows = (
                session.query(cls)
                .filter(cls.status == 'pending', cls.deleted_at.is_(None))
                .order_by(cls.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
                .all()
            )
            return [
                {
                    'id': r.id,
                    'tenant_id': r.tenant_id,
                    'user_id': r.user_id,
                    'offer_id': r.offer_id,
                    'source_url': r.source_url,
                }
                for r in rows
            ]

    @classmethod
    def mark_succeeded(cls, row_id: int, resolved_offer_id: int) -> bool:
        """
        Позначає запит як успішно оброблений.
        Завжди перезаписує offer_id (overwrite ok згідно md).
        """
        with db_session() as session:
            row = session.query(cls).filter_by(id=row_id).first()
            if not row:
                return False
            row.status = 'succeeded'
            row.processed_at = datetime.now()
            row.offer_id = resolved_offer_id
            row.error = None
            row.updated_at = datetime.now()
            session.commit()
            return True

    @classmethod
    def mark_failed(cls, row_id: int, error: str) -> bool:
        """
        Позначає запит як невдалий з описом помилки (≤ 1 КБ — видно користувачу).
        """
        with db_session() as session:
            row = session.query(cls).filter_by(id=row_id).first()
            if not row:
                return False
            row.status = 'failed'
            row.processed_at = datetime.now()
            row.error = str(error)[:1000]
            row.updated_at = datetime.now()
            session.commit()
            return True


# Автоматичне створення таблиць для SQLite
if 'sqlite' in settings.DATABASE_URL:
    Base.metadata.create_all(engine)
