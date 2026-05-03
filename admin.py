from sqladmin import ModelView
from markupsafe import Markup
from models import Product, Cart, Order, OrderItem, User


# -----------------------------
# PRODUCT ADMIN
# -----------------------------
class ProductAdmin(ModelView, model=Product):

    column_list = [
        Product.id,
        Product.name,
        Product.price,
        Product.image,
        Product.category
        
    ]

    column_labels = {
        Product.image: "Image URLs"
    }

    def image(self, obj):
        if obj.image:
            if isinstance(obj.image, list):
                urls = obj.image
            else:
                urls = obj.image.split(",")
            return Markup(f'<img src="/{urls[0]}" width="60">')
        return ""


# -----------------------------
# CART ADMIN
# -----------------------------
class CartAdmin(ModelView, model=Cart):

    column_list = "__all__"


# -----------------------------
# ORDER ADMIN
# -----------------------------
class OrderAdmin(ModelView, model=Order):

    column_list = [
        Order.id,
        Order.full_name,
        Order.phone,
        Order.address,
        Order.total_amount
    ]

    column_details_list = [
        Order.id,
        Order.full_name,
        Order.phone,
        Order.address,
        Order.total_amount,
        Order.items
    ]


# -----------------------------
# ORDER ITEMS ADMIN
# -----------------------------
class OrderItemAdmin(ModelView, model=OrderItem):

    column_list = [
        OrderItem.id,
        OrderItem.order_id,
        OrderItem.product_id,
        OrderItem.size,
        OrderItem.quantity
    ]

class UserAdmin(ModelView, model=User):
    column_list = [User.id, User.username, User.phone, User.userrole, User.password]
