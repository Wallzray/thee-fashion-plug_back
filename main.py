# main.py
from fastapi import FastAPI, Depends, HTTPException, Header, UploadFile, Form, File, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from models import Product, Cart, User, Order, OrderItem
import shutil
import time
import logging
import uuid
import pathlib
import os

from dotenv import load_dotenv
from database import SessionLocal, engine, Base

# Admin UI (sqladmin) imports if used
from admin import ProductAdmin, CartAdmin, OrderAdmin, OrderItemAdmin, UserAdmin
from sqladmin import Admin

# Create app and DB
app = FastAPI()
Base.metadata.create_all(bind=engine)
admin = Admin(app, engine)

# Register admin views (if using sqladmin)
admin.add_view(ProductAdmin)
admin.add_view(UserAdmin)
admin.add_view(OrderAdmin)
admin.add_view(OrderItemAdmin)
admin.add_view(CartAdmin)

# Simple request/response models
class SignupRequest(BaseModel):
    username: str
    phone: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class CheckoutRequest(BaseModel):
    full_name: str
    phone: str
    address: str
    total_amount: float

class StatusUpdate(BaseModel):
    status: str

# DB dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Uploads directory
UPLOAD_DIR = "uploads"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# CORS - include common dev origins; tighten for production
origins = [
    "http://localhost:19006",  # Expo web default
    "http://localhost:8081",
    "http://192.168.0.1:19006"   # alternate dev port
    "http://192.168.0.1:8081"
    "http://127.0.0.1:19006",
    "http://127.0.0.1:8081",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# Simple auth stubs (demo)
# -------------------------
# NOTE: Replace with real JWT/session auth in production.
def get_current_user(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> User:
    """
    Very small demo token parser:
    - Accepts header Authorization: Bearer user-<id>
    - Finds user by id and returns it.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    token = parts[1]
    # token format: "user-<id>"
    if not token.startswith("user-"):
        raise HTTPException(status_code=401, detail="Invalid token format")
    try:
        user_id = int(token.split("-", 1)[1])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user

def require_admin(current_user: User = Depends(get_current_user)):
    if getattr(current_user, "userrole", None) != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
    return current_user

def require_vendor(current_user: User = Depends(get_current_user)):
    if getattr(current_user, "userrole", None) != "vendor":
        raise HTTPException(status_code=403, detail="Vendors only")
    return current_user

# -------------------------
# Utility helpers
# -------------------------
def secure_filename(original: str) -> str:
    ext = pathlib.Path(original).suffix
    return f"{int(time.time())}_{uuid.uuid4().hex}{ext}"

def build_image_url(request: Request, file_path: str) -> str:
    
    base = str(request.base_url).rstrip("/")
    return f"{base}{file_path}"

# -------------------------
# Auth endpoints (demo)
# -------------------------
from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

@app.post("/signup")
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.username == payload.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already taken")
    hashed_pw = hash_password(payload.password)
    new_user = User(username=payload.username, phone=payload.phone, password=hashed_pw, userrole="customer")
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    # Demo token: "user-<id>"
    token = f"user-{new_user.id}"
    return {"message": "Signup successful", "user_id": new_user.id, "token": token}

@app.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = f"user-{user.id}"
    return {"message": "Login successful", "user_id": user.id, "role": user.userrole, "token": token}

# -------------------------
# Product endpoints
# -------------------------

logger = logging.getLogger("uvicorn.error")

@app.post("/products")
async def create_product(
    name: str = Form(...),
    price: float = Form(...),
    image: List[UploadFile] = File(...), # Changed to File for a single upload
    category: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    stored_urls = []
    for image in image:
        content_type = (image.content_type or "").lower()
        if not content_type.startswith("image/"):
            continue # Skip non-images
        
        unique_name = f"{uuid.uuid4().hex}{os.path.splitext(image.filename)[1]}"
        file_location = os.path.join(UPLOAD_DIR, unique_name)
        
        with open(file_location, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
            
        stored_urls.append(f"/uploads/{unique_name}")

    new_product = Product(
        name=name,
        price=price,
        category=category,
        # Store as a JSON-encoded list or comma-separated string
        image=",".join(stored_urls) 
    )
    db.add(new_product)
    db.commit()
    return {"message": "Product saved!", "images": stored_urls}

@app.get("/products")
def get_products(request: Request, category: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Product)
    if category:
        query = query.filter(func.lower(Product.category) == category.lower())
    products = query.all()
    
    result = []
    for product in products:
        # 1. Identify if it's a list or a comma-separated string
        raw_images = []
        if isinstance(product.image, list):
            raw_images = product.image
        elif isinstance(product.image, str):
            # Split by comma and clean up whitespace
            raw_images = [img.strip() for img in product.image.split(",") if img.strip()]
        # Construct a single absolute URL for the image
        image_urls = [build_image_url(request, img) for img in raw_images]

        result.append({
            "id": product.id,
            "name": product.name,
            "price": product.price,
            "category": product.category,
            "image": image_urls # Returns a single string URL
        })
    return result


# -------------------------
# Cart endpoints
# -------------------------
@app.post("/cart")
def add_to_cart(
    product_id: int = Form(...),
    session_id: str = Header(..., alias="X-Session-ID"),
    size: str = Form(...),
    variation: Optional[str] = Form(None),
    quantity: int = Form(...),
    db: Session = Depends(get_db)
):
    new_cart_item = Cart(
        session_id=session_id,
        product_id=product_id,
        variation=variation,
        size=size,
        quantity=quantity
    )
    db.add(new_cart_item)
    db.commit()
    db.refresh(new_cart_item)
    return {"message": "Added to cart", "cart_id": new_cart_item.id}

@app.get("/cart")
def get_cart(request: Request,session_id: str = Header(..., alias="X-Session-ID"), db: Session = Depends(get_db)):
    cart_items = db.query(Cart).filter(Cart.session_id == session_id).all()
    total = 0.0
    items = []
    for item in cart_items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        if not product:
            continue
        subtotal = (product.price or 0) * (item.quantity or 0)
        total += subtotal
        items.append({
            "id": item.id,
            "name": product.name,
            "price": product.price,
            "quantity": item.quantity,
            "size": item.size,
            "variation": item.variation,
            "image_url": build_image_url(request, product.image) if product.image else None,
        })
    return {"items": items, "total_amount": total}

@app.delete("/cart/{item_id}")
def delete_cart_item(item_id: int, session_id: str = Header(..., alias="X-Session-ID"), db: Session = Depends(get_db)):
    item = db.query(Cart).filter(Cart.id == item_id, Cart.session_id == session_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Cart item not found")
    db.delete(item)
    db.commit()
    return {"message": "Deleted"}

# -------------------------
# Checkout and Orders
# -------------------------
@app.post("/checkout", status_code=status.HTTP_201_CREATED)
def checkout(order: CheckoutRequest, session_id: str = Header(..., alias="X-Session-ID"), db: Session = Depends(get_db)):
    try:
        new_order = Order(
            full_name=order.full_name,
            phone=order.phone,
            address=order.address,
            total_amount=order.total_amount,
            status="pending",
            payment_phone=order.phone,
            payment_reference=None 
        )
        db.add(new_order)
        db.flush()  # get id before commit
        logger.info(f"Checkout for session {session_id}, payload={order.dict()}")
        cart_items = db.query(Cart).filter(Cart.session_id == session_id).all()
        logger.info(f"Cart items found: {len(cart_items)}")
        created_items = []
        for item in cart_items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if not product:
                logger.error(f"Product {item.product_id} not found")
                continue
            order_item = OrderItem(
                order_id=new_order.id,
                product_id=product.id,
                size=item.size,
                variation=item.variation,
                quantity=item.quantity,
                price=product.price

            )
            db.add(order_item)
            created_items.append({
                "product_id": product.id,
                "product_name": product.name,
                "image_url": product.image,  # assuming you store image path/URL
                "size": item.size,
                "variation": item.variation,
                "quantity": item.quantity,
                "price": product.price
            })


        # Clear cart
        db.query(Cart).filter(Cart.session_id == session_id).delete()
        db.commit()
        db.refresh(new_order)

        return {
            "message": "Order placed successfully",
            "order_id": new_order.id,
            "full_name": new_order.full_name,
            "phone": new_order.phone,
            "address": new_order.address,
            "total_amount": new_order.total_amount,
            "status": new_order.status,
            "items": created_items
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Checkout failed: {e}")
        raise HTTPException(status_code=500, detail=f"Checkout failed: {str(e)}")
    
@app.get("/orders")
def get_orders(db: Session = Depends(get_db), current_admin: User = Depends(require_admin)):
    orders = db.query(Order).all()
    result = []
    for order in orders:
        result.append({
            "id": order.id,
            "full_name": order.full_name,
            "phone": order.phone,
            "address": order.address,
            "total_amount": order.total_amount,
            "status": order.status,
            "created_at": order.created_at,
            "items": [
                {
                    "product_id": item.product_id,
                    "size": item.size,
                    "quantity": item.quantity,
                    "price": item.price
                }
                for item in order.items
            ]
        })
    return result

@app.put("/orders/{order_id}/status")
def update_order_status(order_id: int, payload: StatusUpdate, db: Session = Depends(get_db), current_admin: User = Depends(require_admin)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    order.status = payload.status
    db.commit()
    db.refresh(order)
    return {"message": "Order status updated", "order_id": order.id, "status": order.status}

load_dotenv()


@app.post("/orders/{order_id}/notify_whatsapp")
async def notify_order_whatsapp(order_id: int, db: Session = Depends(get_db)):
    
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    