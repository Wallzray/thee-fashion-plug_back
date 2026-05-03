from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from database import Base 
from datetime import datetime




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

    full_name = Column(String)
    phone = Column(String)
    address = Column(String)
    total_amount = Column(Float)
    status = Column(String, default="pending")
    payment_phone = Column(String, nullable=True)
    payment_reference = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    items = relationship("OrderItem", back_populates="order")
    def __str__(self):
        return f"Order {self.id}"

class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    size = Column(String)
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