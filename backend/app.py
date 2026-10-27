import os
import psycopg
import requests
import jwt

from datetime import datetime, timedelta, timezone
from pwdlib import PasswordHash
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field

app = FastAPI(
    title="Digital Content Subscription System",
    description="Демонстрационная система управления оплатой и подписками"
    " в сфере цифрового контента",
    version="1.0.0",
)

JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

password_hash = PasswordHash.recommended()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login/form")

PAYMENT_SERVICE_URL = os.getenv(
    "PAYMENT_SERVICE_URL",
    "http://payment-service:8001",
)

SUBSCRIPTION_SERVICE_URL = os.getenv(
    "SUBSCRIPTION_SERVICE_URL",
    "http://subscription-service:8002",
)


class UserRegister(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


def create_access_token(user_id: int) -> str:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET не настроен")

    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": str(user_id),
        "exp": expires_at,
    }

    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)):
    if not JWT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Секретный ключ авторизации не настроен",
        )

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
        )
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=401,
            detail="Недействительный или просроченный токен",
            headers={"WWW-Authenticate": "Bearer"},
        )

    with get_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, email, role "
                "FROM users "
                "WHERE id = %s",
                (user_id,),
            )
            user = cursor.fetchone()

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Пользователь не найден",
        )

    return {
        "id": user[0],
        "name": user[1],
        "email": user[2],
        "role": user[3],
    }


def require_admin(current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для выполнения действия",
        )
    return current_user


class SubscriptionCreate(BaseModel):
    title: str
    description: str
    price: int
    currency: str = "RUB"


def get_database_connection():
    database_url = os.getenv("DATABASE_URL")
    return psycopg.connect(database_url)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "backend",
    }


@app.get("/api/catalog")
def get_catalog():
    with get_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, title, description, price, currency
                FROM subscriptions
                ORDER BY id
                """
            )
            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "title": row[1],
            "description": row[2],
            "price": row[3],
            "currency": row[4],
        }
        for row in rows
    ]


@app.post("/api/catalog", status_code=201)
def create_subscription(
    subscription: SubscriptionCreate,
    current_user: dict = Depends(require_admin),
):
    if not subscription.title.strip():
        raise HTTPException(
            status_code=400,
            detail="Название подписки не может быть пустым",
        )

    if not subscription.description.strip():
        raise HTTPException(
            status_code=400,
            detail="Описание подписки не может быть пустым",
        )

    if subscription.price <= 0:
        raise HTTPException(
            status_code=400,
            detail="Цена должна быть положительной",
        )

    if len(subscription.currency) != 3:
        raise HTTPException(
            status_code=400,
            detail="Код валюты должен состоять из трёх символов",
        )

    with get_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO subscriptions
                    (title, description, price, currency)
                VALUES (%s, %s, %s, %s)
                RETURNING id, title, description, price, currency
                """,
                (
                    subscription.title.strip(),
                    subscription.description.strip(),
                    subscription.price,
                    subscription.currency.upper(),
                ),
            )
            row = cursor.fetchone()

    return {
        "id": row[0],
        "title": row[1],
        "description": row[2],
        "price": row[3],
        "currency": row[4],
    }


class PurchaseRequest(BaseModel):
    plan_id: int
    simulate_success: bool = True


@app.post("/api/purchase", status_code=201)
def purchase_subscription(
    purchase: PurchaseRequest,
    current_user: dict = Depends(get_current_user),
):
    with get_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, title, price, currency
                FROM subscriptions
                WHERE id = %s
                """,
                (purchase.plan_id,),
            )
            plan = cursor.fetchone()

    if plan is None:
        raise HTTPException(
            status_code=404,
            detail="Тариф не найден",
        )

    plan_id, title, price, currency = plan

    try:
        payment_response = requests.post(
            f"{PAYMENT_SERVICE_URL}/pay",
            json={
                "amount": price,
                "simulate_success": purchase.simulate_success,
            },
            timeout=10,
        )
        payment_response.raise_for_status()
        payment = payment_response.json()
    except requests.RequestException:
        raise HTTPException(
            status_code=502,
            detail="Сервис оплаты временно недоступен",
        )

    if payment.get("status") != "success":
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Оплата отклонена. Подписка не создана",
                "payment": payment,
            },
        )

    try:
        subscription_response = requests.post(
            f"{SUBSCRIPTION_SERVICE_URL}/subscriptions",
            json={
                "user_id": current_user["id"],
                "plan_name": title,
                "duration_days": 30,
            },
            timeout=10,
        )
        subscription_response.raise_for_status()
        user_subscription = subscription_response.json()
    except requests.RequestException:
        raise HTTPException(
            status_code=502,
            detail=(
                "Оплата прошла успешно, но создать подписку не удалось. "
                "Требуется проверить результат операции."
            ),
        )

    return {
        "message": "Оплата прошла успешно, подписка оформлена",
        "payment": payment,
        "subscription": user_subscription,
    }


@app.post("/api/register", status_code=201)
def register_user(data: UserRegister):
    name = data.name.strip()
    email = str(data.email).strip().lower()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Имя не может быть пустым",
        )

    hashed_password = password_hash.hash(data.password)

    try:
        with get_database_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (name, email, password_hash)
                    VALUES (%s, %s, %s)
                    RETURNING id, name, email
                    """,
                    (name, email, hashed_password),
                )
                user = cursor.fetchone()

    except psycopg.errors.UniqueViolation:
        raise HTTPException(
            status_code=409,
            detail="Пользователь с такой почтой уже зарегистрирован",
        )

    return {
        "message": "Регистрация прошла успешно",
        "user": {
            "id": user[0],
            "name": user[1],
            "email": user[2],
        },
    }


@app.post("/api/login", response_model=TokenResponse)
def login_user(data: UserLogin):
    email = str(data.email).strip().lower()

    with get_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, password_hash
                FROM users
                WHERE email = %s
                """,
                (email,),
            )
            user = cursor.fetchone()

    if user is None or not password_hash.verify(
        data.password,
        user[1],
    ):
        raise HTTPException(
            status_code=401,
            detail="Неверная почта или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user[0])

    return {
        "access_token": token,
        "token_type": "bearer",
    }


@app.post("/api/login/form", response_model=TokenResponse)
def login_user_form(
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    email = form_data.username.strip().lower()

    with get_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, password_hash
                FROM users
                WHERE email = %s
                """,
                (email,),
            )
            user = cursor.fetchone()

    if user is None or not password_hash.verify(
        form_data.password,
        user[1],
    ):
        raise HTTPException(
            status_code=401,
            detail="Неверная почта или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "access_token": create_access_token(user[0]),
        "token_type": "bearer",
    }


@app.get("/api/me")
def get_me(current_user: dict = Depends(get_current_user)):
    return current_user


@app.get("/api/my-subscriptions")
def get_my_subscriptions(
    current_user: dict = Depends(get_current_user),
):
    with get_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, plan_name, start_date, end_date, status
                FROM user_subscriptions
                WHERE user_id = %s
                ORDER BY id DESC
                """,
                (current_user["id"],),
            )
            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "plan_name": row[1],
            "start_date": row[2].isoformat(),
            "end_date": row[3].isoformat(),
            "status": row[4],
        }
        for row in rows
    ]


@app.post("/api/my-subscriptions/{subscription_id}/cancel")
def cancel_my_subscription(
    subscription_id: int,
    current_user: dict = Depends(get_current_user),
):
    with get_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status
                FROM user_subscriptions
                WHERE id = %s AND user_id = %s
                """,
                (subscription_id, current_user["id"]),
            )
            row = cursor.fetchone()

            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail="Подписка не найдена",
                )

            if row[0] != "active":
                raise HTTPException(
                    status_code=400,
                    detail="Отменить можно только активную подписку",
                )

            cursor.execute(
                """
                UPDATE user_subscriptions
                SET status = 'cancelled'
                WHERE id = %s AND user_id = %s
                """,
                (subscription_id, current_user["id"]),
            )

    return {"message": "Подписка успешно отменена"}


@app.get("/api/admin/subscriptions")
def get_all_subscriptions(
    current_user: dict = Depends(require_admin),
):
    try:
        response = requests.get(
            f"{SUBSCRIPTION_SERVICE_URL}/subscriptions",
            timeout=5,
        )
        response.raise_for_status()
        subscriptions = response.json()
    except requests.RequestException:
        raise HTTPException(
            status_code=502,
            detail="Не удалось получить список подписок",
        )

    user_ids = list({
        subscription["user_id"]
        for subscription in subscriptions
    })

    if not user_ids:
        return []

    with get_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, email
                FROM users
                WHERE id = ANY(%s)
                """,
                (user_ids,),
            )
            users = cursor.fetchall()

    users_by_id = {
        user[0]: {
            "user_name": user[1],
            "user_email": user[2],
        }
        for user in users
    }

    result = []

    for subscription in subscriptions:
        user_info = users_by_id.get(
            subscription["user_id"],
            {
                "user_name": "Неизвестный пользователь",
                "user_email": "—",
            },
        )

        result.append({
            **subscription,
            **user_info,
        })

    return result
