# main.py
from fastapi import APIRouter, FastAPI, Depends, HTTPException, Header, UploadFile, Form, File, Request, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from models import Product, Cart, User, Order, OrderItem
import shutil, time, logging, uuid, pathlib, os, httpx
from datetime import datetime, timezone
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
from database import SessionLocal, engine, Base
from admin import ProductAdmin, CartAdmin, OrderAdmin, OrderItemAdmin, UserAdmin
from sqladmin import Admin

# Create app and DB
app = FastAPI()
Base.metadata.create_all(bind=engine)
admin = Admin(app, engine)
router = APIRouter()

# Register admin views (if using sqladmin)
admin.add_view(ProductAdmin)
admin.add_view(UserAdmin)
admin.add_view(OrderAdmin)
admin.add_view(OrderItemAdmin)
admin.add_view(CartAdmin)

load_dotenv()

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

class PesapalCreateRequest(BaseModel):
    order_id: int

class CartItemSchema(BaseModel):
    product_id: int
    size: str
    variation: Optional[str] = None
    quantity: int
    user_id: Optional[int] = None
    session_id: Optional[str] = None

    class Config:
        from_attributes = True

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
    "https://thee-fashion-plug-front.vercel.app",
    "http://localhost:19006",  # Expo web default
    "http://localhost:8081",
    "http://192.168.0.1:19006",   # alternate dev port
    "http://192.168.0.1:8081",
    "http://127.0.0.1:19006",
    "http://127.0.0.1:8081"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins= ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

PESAPAL_CONSUMER_KEY = os.getenv("PESAPAL_CONSUMER_KEY")
PESAPAL_CONSUMER_SECRET = os.getenv("PESAPAL_CONSUMER_SECRET")
PESAPAL_BASE = os.getenv("PESAPAL_BASE", "https://pay.pesapal.com/v3")
CALLBACK_URL = os.getenv("CALLBACK_URL")
IPN_ID = os.getenv("IPN_ID")

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

@app.get("/products/featured")
def get_featured_products(request: Request, db: Session = Depends(get_db)):
    products = db.query(Product).filter(Product.category == "featured").all()
    result = []
    for product in products:
        raw_images = [img.strip() for img in product.image.split(",") if img.strip()]
        image_url = build_image_url(request, raw_images[0]) if raw_images else None
        result.append({
            "id": product.id,
            "name": product.name,
            "price": product.price,
            "image": image_url
        })
    return result

# -------------------------
# Cart endpoints
# -------------------------
@app.post("/cart", status_code=status.HTTP_201_CREATED)
async def add_to_cart(item: CartItemSchema, db: Session = Depends(get_db)):
    try:
        existing_item = db.query(Cart).filter(
            Cart.product_id == item.product_id,
            Cart.size == item.size,
            Cart.variation == item.variation,
            Cart.session_id == item.session_id
        ).first()

        if existing_item:
            existing_item.quantity = item.quantity
        else:
            new_item = Cart(
                product_id=item.product_id,
                size=item.size,
                variation=item.variation,
                quantity=item.quantity,
                session_id=item.session_id
            )

            db.add(new_item)

        db.commit()

        return {
            "success": True,
            "message": "Item added to cart"
        }

    except Exception as e:
        db.rollback()
        print(f"Cart Error: {e}")

        raise HTTPException(
            status_code=500,
            detail=f"Could not add item: {str(e)}"
        )
   

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
        raw_images = []
        if isinstance(product.image, str):
            raw_images = [img.strip() for img in product.image.split(",") if img.strip()]
            image_url = build_image_url(request, raw_images[0]) if raw_images else None
        items.append({
            "id": item.id,
            "name": product.name,
            "price": product.price,
            "quantity": item.quantity,
            "size": item.size,
            "variation": item.variation,
            "image_url": image_url,
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
async def checkout(
    order: CheckoutRequest, 
    session_id: str = Header(..., alias="X-Session-ID"), 
    db: Session = Depends(get_db)
):
    try:
        # 1. Create the Order Record
        new_order = Order(
            session_id=session_id,
            full_name=order.full_name,
            phone=order.phone,
            address=order.address,
            total_amount=order.total_amount,
            status="PENDING",  
            merchant_reference=None,
            order_tracking_id=None,
        )
        db.add(new_order)
        db.flush()  # Populates new_order.id

        # 2. Populate Order Items from Cart
        cart_items = db.query(Cart).filter(Cart.session_id == session_id).all()
        created_items = []
        for item in cart_items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if not product:
                continue
            order_item = OrderItem(
                order_id=new_order.id,
                product_id=product.id,
                product_name=product.name,
                size=item.size,
                variation=item.variation,
                quantity=item.quantity,
                price=product.price
            )
            db.add(order_item)
            created_items.append({
                "product_id": product.id,
                "product_name": product.name,
                "quantity": item.quantity,
                "price": product.price,
                "variation": item.variation
            })

        # 3. Generate PesaPal Parameters right here
        merchant_reference = f"ORDER-{new_order.id}-{int(time.time())}"
        new_order.merchant_reference = merchant_reference

        # 4. Fetch your PesaPal Token
        token_resp = await request_pesapal_token()
        token = token_resp if isinstance(token_resp, str) else token_resp.get("token") or token_resp.get("access_token")
        
        # 5. Build the official nested PesaPal Payload
        pesapal_payload = {
            "id": str(merchant_reference),
            "amount": float(new_order.total_amount),
            "currency": "UGX",
            "description": f"Thee Fashion Plug Order {new_order.id}",
            "callback_url": "https://thee-fashion-plug-back.onrender.com/pesapal/callback",
            "redirect_mode": "",
            "notification_id": IPN_ID, 
            "billing_address": {
                "first_name": new_order.full_name.split(" ")[0] if new_order.full_name else "Client",
                "last_name": " ".join(new_order.full_name.split(" ")[1:]) if new_order.full_name else "Plug",
                "phone_number": new_order.phone if new_order.phone else "",
                "email_address": "toptechugltd@gmail.com",
                "country_code": "UG"
            }
        }

        # 6. Handshake with PesaPal
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{PESAPAL_BASE}/api/Transactions/SubmitOrderRequest",
                json=pesapal_payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json","Accept": "application/json"}
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"Pesapal Error ({resp.status_code}): {resp.text}"
                )
            pesapal_data = resp.json()


        # 7. Update order with tracking information
        order_tracking_id = pesapal_data.get("orderTrackingId") or pesapal_data.get("order_tracking_id")
        new_order.order_tracking_id = order_tracking_id
        new_order.raw_response = str(pesapal_data)
        
        # Final safe database save
        db.commit()
        db.refresh(new_order)

        # 8. Return everything including the payment URL to the frontend
        return {
            "message": "Order initiated successfully",
            "order_id": new_order.id,
            "payment_url": pesapal_data.get("redirect_url") or pesapal_data.get("payment_url"),
            "order_tracking_id": order_tracking_id,
            "total_amount": new_order.total_amount,
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
            "order_id": order.merchant_reference,
            "full_name": order.full_name,
            "phone": order.phone,
            "address": order.address,
            "total_amount": order.total_amount,
            "status": order.status,
            "created_at": order.paid_at,
            "items": [
                {
                    "product_id": item.product_id,
                    "size": item.size,
                    "quantity": item.quantity,
                    "price": item.price,
                    "variation": item.variation
                }
                for item in order.items
            ]
        })
    return result


@app.get("/orders/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    items = []
    for item in order.items:  # assuming relationship set up
        product = db.query(Product).filter(Product.id == item.product_id).first()
        items.append({
            "product_id": item.product_id,
            "product_name": product.name if product else "Unknown",
            "quantity": item.quantity,
            "size": item.size,
            "price": item.price,
            "variation": item.variation
        })

    return {
        "order_id": order.id,
        "merchant_reference": order.merchant_reference,
        "order_tracking_id": order.order_tracking_id,
        "status": order.status,
        "total_amount": order.total_amount,
        "items": items,
    }


@app.put("/orders/{order_id}/status")
def update_order_status(order_id: int, payload: StatusUpdate, db: Session = Depends(get_db), current_admin: User = Depends(require_admin)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    order.status = payload.status
    db.commit()
    db.refresh(order)
    return {"message": "Order status updated", "order_id": order.id, "status": order.status}




@app.post("/orders/{order_id}/notify_whatsapp")
async def notify_order_whatsapp(order_id: int, db: Session = Depends(get_db)):
    
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
 

async def request_pesapal_token():
    url = f"{PESAPAL_BASE}/api/Auth/RequestToken"
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(url, json={
            "consumer_key": PESAPAL_CONSUMER_KEY,
            "consumer_secret": PESAPAL_CONSUMER_SECRET
        })
        resp.raise_for_status()
        data = resp.json()
        token = data.get("token") or data.get("access_token") or data
        return token

    #Incase of any errors, you can return the raw response for debugging 
    # return {"payment_url": payment_url, "order_id": order.id, "orderTrackingId": order.order_tracking_id, "raw": data}

async def check_live_payment_status(order_tracking_id: str, token: str) -> dict:
    """Queries PesaPal for the absolute, definitive status of a specific transaction."""
    # Note: Correct path structure for status checks includes /api/
    url = f"{PESAPAL_BASE}/api/Transactions/GetTransactionStatus?orderTrackingId={order_tracking_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    async with httpx.AsyncClient(verify=False) as client:
        response = await client.get(url, headers=headers, timeout=10.0)
        if response.status_code != 200:
            logger.error(f"Failed to query transaction status for {order_tracking_id}: {response.text}")
            raise HTTPException(status_code=500, detail="Failed to fetch transaction records")
        return response.json()

# --- THE LIVE INTEGRATED CALLBACK ROUTE ---

@app.get("/pesapal/callback", response_class=HTMLResponse)
async def pesapal_callback(request: Request, db: Session = Depends(get_db)):
    # 1. Parse inbound request query variables
    orderTrackingId = request.query_params.get("OrderTrackingId") or request.query_params.get("orderTrackingId")
    merchantRef = request.query_params.get("OrderMerchantReference") or request.query_params.get("merchant_reference")
    
    logger.info(f"Callback intercept received -> Tracking ID: {orderTrackingId}, Ref: {merchantRef}")
    
    if not orderTrackingId:
        raise HTTPException(status_code=400, detail="Missing order tracking token identifier")

    try:
        # 2. Get live token & run your check status workflow
        token = await request_pesapal_token()
        status_data = await check_live_payment_status(orderTrackingId, token)
        
        pesapal_status = status_data.get("payment_status_description", "UNKNOWN").upper()
        payment_method = status_data.get("payment_method", "N/A")
        amount = status_data.get("amount", 0.0)
    except Exception as e:
        logger.exception(f"Error communicating with PesaPal gateway: {e}")
        return render_status_page(False, "Error", "Unable to securely verify your payment status with PesaPal.", merchantRef)

    # 3. Locate the target user order record inside your SQLite database
    order = db.query(Order).filter(Order.order_tracking_id == orderTrackingId).first()
    if not order and merchantRef:
        order = db.query(Order).filter(Order.merchant_reference == merchantRef).first()

    if not order:
        logger.error(f"Order records not found for Tracking ID: {orderTrackingId} or Ref: {merchantRef}")
        return render_status_page(False, "Order Not Found", "Your payment went through, but we couldn't match it to an active checkout session.", merchantRef)

    # 4. Synchronize database states based on payment gateway realities
    order.status = pesapal_status
    order.raw_response = str(status_data)

    if pesapal_status in {"COMPLETED", "SUCCESS"}:
        order.paid_at = datetime.now(timezone.utc)
        # Clear shopping cart contents if a session hook exists
        if order.session_id:
            db.query(Cart).filter(Cart.session_id == order.session_id).delete()
        
        db.commit()
        db.refresh(order)
        return render_status_page(True, "Payment Successful!", f"Thank you! We received your payment of UGX {amount:,.0f} via {payment_method}.", merchantRef)
    elif pesapal_status == "PENDING":
        order.status = "ABORTED_OR_PENDING"
        db.commit()
        return render_status_page(False, "Payment Incomplete", "It looks like the payment process was closed or cancelled.", merchantRef)
    else:
        # Handles instances of standard rejections, timeouts, or user cancellations
        db.commit()
        return render_status_page(False, f"Payment {pesapal_status.title()}", f"Your transaction could not be completed (Status: {pesapal_status}). No funds were deducted.", merchantRef)

# --- UI HELPER: RENDERS CLEAN RESPONSIVE HTML PAGE ---
def render_status_page(is_success: bool, title: str, message: str, reference: str) -> str:
   frontend_redirect_url = f"https://thee-fashion-plug-front.vercel.app/checkout-status?ref={reference}&status={'success' if is_success else 'failed'}"
   return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Processing Payment...</title>
        <script>
            // 🎯 THE DESKTOP WEB CUT-OFF:
            // This immediately halts any further backend loading and snaps the user 
            // back into your local frontend application layout!

            //window.location.href = "{frontend_redirect_url}";
        </script>
    </head>
    <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
        <h2>Verifying your payment state...</h2>
        <p>{message}</p>
        <p><strong>Reference:</strong> {reference}</p>
        <p>If you are not redirected automatically, <a href="{frontend_redirect_url}">click here</a>.</p>
    </body>
    </html>
    """

@app.post("/pesapal/ipn")
async def pesapal_ipn(request: Request, background_tasks: BackgroundTasks):
   
    payload = await request.json()
    
    background_tasks.add_task(process_ipn_update, payload)
    
    # 3. Always acknowledge receipt immediately
    return {"status": "acknowledged"}

async def process_ipn_update(payload: dict):
    order_id = payload.get("OrderTrackingId")
    merchant_ref = payload.get("OrderMerchantReference")

    token = await request_pesapal_token()
    status_data = await check_live_payment_status(order_id, token)
    new_status = status_data.get("payment_status_description")
    
    print(f"IPN processed for {merchant_ref}: New status is {new_status}")