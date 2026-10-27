import os
import psycopg

from datetime import date, timedelta
from enum import Enum
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


app = FastAPI(
    title="Subscription Management Service",
    description="Сервис управления пользовательскими подписками",
    version="1.0.0",
)


def get_database_connection():
    database_url = os.getenv("DATABASE_URL")
    return psycopg.connect(database_url)


class SubscriptionStatus(str, Enum):
    active = "active"
    expired = "expired"
    cancelled = "cancelled"


class SubscriptionCreate(BaseModel):
    user_id: int = Field(gt=0)
    plan_name: str = Field(min_length=1, max_length=150)
    duration_days: int = Field(default=30, gt=0)


def row_to_dict(row):
    return {
        "id": row[0],
        "user_id": row[1],
        "plan_name": row[2],
        "start_date": row[3],
        "end_date": row[4],
        "status": row[5],
    }


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "subscription-service",
    }


@app.post("/subscriptions", status_code=201)
def create_subscription(data: SubscriptionCreate):
    if not data.plan_name.strip():
        raise HTTPException(
            status_code=400,
            detail="Название тарифа не может быть пустым",
        )

    start = date.today()
    end = start + timedelta(days=data.duration_days)

    with get_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO user_subscriptions
                    (user_id, plan_name, start_date, end_date, status)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, user_id, plan_name, start_date, end_date, status
                """,
                (
                    data.user_id,
                    data.plan_name.strip(),
                    start,
                    end,
                    SubscriptionStatus.active.value,
                ),
            )
            row = cursor.fetchone()

    return row_to_dict(row)


@app.get("/subscriptions")
def get_subscriptions():
    today = date.today()

    with get_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE user_subscriptions
                SET status = %s
                WHERE status = %s AND end_date < %s
                """,
                (
                    SubscriptionStatus.expired.value,
                    SubscriptionStatus.active.value,
                    today,
                ),
            )

            cursor.execute(
                """
                SELECT id, user_id, plan_name, start_date, end_date, status
                FROM user_subscriptions
                ORDER BY id
                """
            )
            rows = cursor.fetchall()

    return [row_to_dict(row) for row in rows]


@app.get("/subscriptions/{subscription_id}")
def get_subscription(subscription_id: int):
    with get_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, user_id, plan_name, start_date, end_date, status
                FROM user_subscriptions
                WHERE id = %s
                """,
                (subscription_id,),
            )
            row = cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Подписка не найдена",
        )

    return row_to_dict(row)


@app.post("/subscriptions/{subscription_id}/cancel")
def cancel_subscription(subscription_id: int):
    with get_database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE user_subscriptions
                SET status = %s
                WHERE id = %s
                RETURNING id, user_id, plan_name, start_date, end_date, status
                """,
                (
                    SubscriptionStatus.cancelled.value,
                    subscription_id,
                ),
            )
            row = cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Подписка не найдена",
        )

    return row_to_dict(row)
