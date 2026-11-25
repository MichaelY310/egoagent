"""A small custom Tool: schema + function, no runtime-specific code."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def quote_total(quantity: int, unit_price: float, discount_percent: float = 0):
    if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 1_000_000:
        raise ValueError("quantity must be an integer between 1 and 1000000")
    try:
        price, discount = Decimal(str(unit_price)), Decimal(str(discount_percent))
    except InvalidOperation as error:
        raise ValueError("price and discount must be finite numbers") from error
    if not price.is_finite() or not 0 <= price <= Decimal("1000000000"):
        raise ValueError("unit_price must be finite and between 0 and 1000000000")
    if not discount.is_finite() or not 0 <= discount <= 100:
        raise ValueError("discount_percent must be between 0 and 100")
    subtotal = price * quantity
    total = (subtotal * (100 - discount) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"quantity": quantity, "subtotal": str(subtotal), "discount_percent": str(discount), "total": str(total)}
