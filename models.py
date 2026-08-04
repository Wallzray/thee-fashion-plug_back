from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime,Text
from sqlalchemy.orm import relationship
from database import Base 



class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    image = Column(String, nullable=False)   # store image URL or path 
    category = Column(String, nullable=True)  # new category field

    order_items = relationship("OrderItem", back_populates="product")
    def __str__(self):
        return self.name


class Cart(Base):
    __tablename__ = "cart"

    id = Column(Integer, primary_key=True)
    session_id = Column(String, index=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    variation = Column(String, nullable=True)
    size = Column(String)
    quantity = Column(Integer)

    product = relationship("Product")

    def __str__(self):
        return f"Cart Item {self.id}"

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True)
    full_name = Column(String)
    phone = Column(String)
    address = Column(String)
    total_amount = Column(Float)
    
    merchant_reference = Column(String(128), unique=True, index=True)
    order_tracking_id = Column(String(256), unique=True, index=True, nullable=True)
    status = Column(String(64), default="PENDING") 
    paid_at = Column(DateTime, nullable=True)

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    def __str__(self):
        return f"Order {self.id}"

class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    product_name = Column(String)
    size = Column(String)
    variation = Column(String, nullable=True)
    quantity = Column(Integer)
    price = Column(Float)
    
    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")

    def __str__(self):
        return f"{self.product}"
    

class User(Base): 
    __tablename__ = "users" 
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True) 
    phone = Column(String, unique=True) 
    password = Column(String)
    userrole = Column(String, default="customer")