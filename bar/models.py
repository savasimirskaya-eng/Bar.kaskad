# models.py
from pydantic import BaseModel
from typing import List

class OrderRequest(BaseModel):
    name: str

class MixRequest(BaseModel):
    ingredients: List[str] = []

class TipRequest(BaseModel):
    amount: int