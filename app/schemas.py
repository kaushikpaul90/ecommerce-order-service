from pydantic import BaseModel, Field

class OrderRequest(BaseModel):
    item: str
    quantity: int = Field(gt=0, description="Quantity must be greater than zero")
