from pydantic import BaseModel

class CheckoutRequest(BaseModel): 
    full_name: str
    phone: str
    address: str
    total_amount: float
