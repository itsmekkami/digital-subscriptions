from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(
    title="Test Payment Service",
    description="Сервис имитации оплаты подписок в сфере цифрового контента",
    version="1.0.0",
)


class PaymentRequest(BaseModel):
    amount: int
    simulate_success: bool = True


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "payment-service",
    }


@app.post("/pay")
def process_payment(payment: PaymentRequest):
    if payment.amount <= 0:
        return {
            "status": "failed",
            "message": "Сумма платежа должна быть положительной",
        }

    if payment.simulate_success:
        return {
            "status": "success",
            "message": "Тестовый платёж успешно выполнен",
            "amount": payment.amount,
            "currency": "RUB",
        }

    return {
        "status": "failed",
        "message": "Тестовый платёж отклонён",
        "amount": payment.amount,
        "currency": "RUB",
    }
