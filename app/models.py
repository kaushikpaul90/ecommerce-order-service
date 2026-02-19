from sqlalchemy import Column, Integer, String
from app.database import Base

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    item = Column(String)
    quantity = Column(Integer, nullable=False)
    status = Column(String)
