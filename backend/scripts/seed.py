#!/usr/bin/env python
"""초기 데이터 시드 스크립트 (멱등).

    cd backend
    python scripts/seed.py            # 관리자 계정만 보장
    python scripts/seed.py --demo     # + 화면 확인용 예시 식당/거래

- `.env` 의 ADMIN_EMAIL / ADMIN_PASSWORD / ADMIN_NAME 으로 관리자 계정을 보장한다.
- **이미 있는 계정의 비밀번호는 절대 덮어쓰지 않는다.**
- `--demo` 는 이미 예시 데이터가 있으면 아무 것도 하지 않는다.

⚠️ `--demo` 는 개발/시연용이다. 운영 DB 에는 쓰지 말 것.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ── 출력 인코딩 보정 ────────────────────────────────────────────────
# Windows 에서 stdout 이 파이프/리다이렉트되면 인코딩이 로케일(cp949)로 잡혀
# 한국어는 깨지고 ✅ 같은 기호는 UnicodeEncodeError 로 스크립트를 죽인다.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError, OSError):  # pragma: no cover - 환경 의존
        pass

# ── import 경로 보정: `python scripts/seed.py` 로 실행해도 `import app...` 이 되게 ──
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import func, inspect, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.db import SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.core.timeutil import KST, to_utc_naive  # noqa: E402
from app.models import (  # noqa: E402
    SIGNED_AMOUNT_SQL,
    Restaurant,
    Transaction,
    TxType,
    User,
    UserRole,
)

# ──────────────────────────────────────────────────────────────────
#  예시 데이터 (전부 가상. 실제 상호/사업자번호/전화번호가 아니다)
#  days: 오늘로부터 며칠 전 (KST 기준) · hour: KST 시각
# ──────────────────────────────────────────────────────────────────
DEMO_RESTAURANTS: list[dict] = [
    {
        "name": "행복분식",
        "business_number": "6011000011",
        "address": "전북 전주시 덕진구 백제대로 123 1층",
        "phone": "063-100-1001",
        "memo": "연구실에서 도보 5분. 점심 백반·돈까스.",
        "charges": [
            (58, 12, 300_000, "선결제 30만원 (계좌이체)"),
            (12, 13, 200_000, "잔액 부족해서 추가 선결제"),
        ],
        "uses": [
            (58, 12, 42_000, "점심 4인"),
            (51, 12, 38_000, "점심 3인"),
            (44, 19, 55_000, "저녁 세미나 후"),
            (37, 12, 47_000, "점심 4인"),
            (30, 19, 61_000, "논문 마감 야식"),
            (23, 12, 39_000, "점심 3인"),
            (16, 12, 44_000, "점심 4인"),
            (9, 19, 51_000, "저녁 4인"),
            (3, 12, 36_000, "점심 3인"),
        ],
    },
    {
        "name": "든든한식당",
        "business_number": "6011000022",
        "address": "전북 전주시 덕진구 명륜3길 45",
        "phone": "063-100-2002",
        "memo": "단체석 있음. 회식용. 예약 필요.",
        "charges": [
            (45, 18, 200_000, "회식용 선결제 20만원"),
        ],
        "uses": [
            (45, 19, 63_000, "신입생 환영 회식"),
            (31, 19, 58_000, "학회 준비 회식"),
            (18, 19, 55_000, "졸업 축하 회식"),
        ],
    },
    {
        "name": "청춘국수",
        "business_number": "6011000033",
        "address": "전북 전주시 덕진구 기린대로 210",
        "phone": None,
        "memo": "혼밥 가능. 국수·비빔밥.",
        "charges": [
            (20, 12, 150_000, "선결제 15만원 (현금)"),
        ],
        "uses": [
            (20, 12, 28_000, "점심 2인"),
            (10, 12, 33_000, "점심 3인"),
            (4, 13, 26_000, "점심 2인"),
        ],
    },
]

DEMO_BUSINESS_NUMBERS = [r["business_number"] for r in DEMO_RESTAURANTS]


def _kst_ago(days: int, hour: int) -> datetime:
    """며칠 전 KST 벽시계 시각 → DB 저장용 naive UTC."""
    kst_now = datetime.now(KST)
    target = (kst_now - timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0, tzinfo=None
    )
    return to_utc_naive(target)


def _check_schema() -> bool:
    """테이블이 없으면 alembic 안내 후 중단."""
    if inspect(engine).has_table(User.__tablename__):
        return True
    print("❌ DB 테이블이 없습니다. 마이그레이션을 먼저 실행하세요:")
    print()
    print("      cd backend && alembic upgrade head")
    print()
    print(f"   (DB: {settings.sqlalchemy_url})")
    return False


def ensure_admin(db: Session) -> tuple[User, str]:
    """ADMIN_* 설정의 관리자 계정을 보장. (user, 수행한 일) 반환."""
    email = settings.admin_email.strip().lower()
    existing = db.scalar(select(User).where(func.lower(User.email) == email))

    if existing is None:
        user = User(
            email=email,
            name=settings.admin_name,
            password_hash=hash_password(settings.admin_password),
            role=UserRole.admin,
            is_active=True,
        )
        db.add(user)
        db.commit()
        return user, "created"

    # 이미 있는 계정: 비밀번호는 절대 건드리지 않고, 권한/활성만 보정한다.
    changes: list[str] = []
    if existing.role != UserRole.admin:
        existing.role = UserRole.admin
        changes.append("role=admin")
    if not existing.is_active:
        existing.is_active = True
        changes.append("is_active=true")
    if changes:
        db.commit()
        return existing, "promoted:" + ",".join(changes)
    return existing, "exists"


def demo_exists(db: Session) -> bool:
    return (
        db.scalar(
            select(func.count())
            .select_from(Restaurant)
            .where(Restaurant.business_number.in_(DEMO_BUSINESS_NUMBERS))
        )
        or 0
    ) > 0


def seed_demo(db: Session, admin: User) -> dict:
    """예시 식당 + 거래 삽입. 이미 있으면 아무 것도 하지 않는다."""
    if demo_exists(db):
        return {"skipped": True}

    made_restaurants = 0
    made_charges = 0
    made_uses = 0

    for spec in DEMO_RESTAURANTS:
        restaurant = Restaurant(
            name=spec["name"],
            business_number=spec["business_number"],
            address=spec["address"],
            phone=spec["phone"],
            memo=spec["memo"],
            is_archived=False,
            created_by=admin.id,
        )
        db.add(restaurant)
        db.flush()  # id 확보
        made_restaurants += 1

        for days, hour, amount, memo in spec["charges"]:
            db.add(
                Transaction(
                    restaurant_id=restaurant.id,
                    type=TxType.CHARGE,
                    amount=amount,
                    occurred_at=_kst_ago(days, hour),
                    memo=memo,
                    created_by=admin.id,
                )
            )
            made_charges += 1

        for days, hour, amount, memo in spec["uses"]:
            db.add(
                Transaction(
                    restaurant_id=restaurant.id,
                    type=TxType.USE,
                    amount=amount,
                    occurred_at=_kst_ago(days, hour),
                    memo=memo,
                    created_by=admin.id,
                )
            )
            made_uses += 1

    db.commit()
    return {
        "skipped": False,
        "restaurants": made_restaurants,
        "charges": made_charges,
        "uses": made_uses,
    }


def _won(n: int) -> str:
    return f"{n:,}원"


def report_balances(db: Session) -> None:
    """현재 식당별 잔액 요약 — 잔액 컬럼은 없고 항상 원장 합계로 계산한다."""
    rows = db.execute(
        select(
            Restaurant.name,
            func.coalesce(func.sum(SIGNED_AMOUNT_SQL), 0),
        )
        .outerjoin(
            Transaction,
            (Transaction.restaurant_id == Restaurant.id) & (Transaction.voided_at.is_(None)),
        )
        .where(Restaurant.is_archived.is_(False))
        .group_by(Restaurant.id, Restaurant.name)
        .order_by(Restaurant.name)
    ).all()

    if not rows:
        print("   (등록된 식당이 없습니다)")
        return

    total = 0
    for name, balance in rows:
        balance = int(balance or 0)
        total += balance
        low = " ⚠️ 잔액 부족" if balance < settings.low_balance_threshold else ""
        print(f"   · {name}: {_won(balance)}{low}")
    print(f"   ── 총 잔액: {_won(total)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="seed.py",
        description="관리자 계정을 보장하고, 선택적으로 예시 데이터를 넣습니다 (멱등).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "예시:\n"
            "  python scripts/seed.py            관리자 계정만 보장\n"
            "  python scripts/seed.py --demo     + 예시 식당 3곳과 최근 두 달치 거래\n"
        ),
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="화면 확인용 예시 식당/거래를 추가 (이미 있으면 아무 것도 하지 않음). 운영 DB 에는 쓰지 마세요.",
    )
    args = parser.parse_args(argv)

    print("=" * 62)
    print(" 연구실 선결제 관리 — 초기 데이터 시드")
    print("=" * 62)
    print(f" DB : {settings.sqlalchemy_url}")
    print(f" 모드: {'관리자 + 예시 데이터(--demo)' if args.demo else '관리자만'}")
    print("-" * 62)

    if not _check_schema():
        return 1

    if len(settings.admin_password) < 8:
        print("⚠️  ADMIN_PASSWORD 가 8자 미만입니다. 웹 가입 규칙(8자 이상)과 어긋납니다.")
        print("   .env 의 ADMIN_PASSWORD 를 더 긴 값으로 바꾸는 것을 권합니다.")

    with SessionLocal() as db:
        admin, what = ensure_admin(db)

        if what == "created":
            print(f"✅ 관리자 계정을 생성했습니다: {admin.email} ({admin.name})")
            print("   비밀번호는 .env 의 ADMIN_PASSWORD 값입니다. 로그인 후 바로 변경하세요.")
        elif what.startswith("promoted:"):
            print(f"✅ 기존 계정을 관리자로 보정했습니다: {admin.email} ({what[9:]})")
            print("   비밀번호는 그대로 유지했습니다.")
        else:
            print(f"ℹ️  관리자 계정이 이미 있습니다: {admin.email} ({admin.name})")
            print("   비밀번호는 덮어쓰지 않았습니다.")

        user_count = db.scalar(select(func.count()).select_from(User)) or 0
        print(f"   전체 사용자: {user_count}명")

        if args.demo:
            print("-" * 62)
            result = seed_demo(db, admin)
            if result["skipped"]:
                print("ℹ️  예시 데이터가 이미 있습니다. 추가하지 않았습니다.")
            else:
                print(
                    f"✅ 예시 데이터를 넣었습니다: "
                    f"식당 {result['restaurants']}곳 · "
                    f"충전 {result['charges']}건 · 사용 {result['uses']}건"
                )
                print("   (최근 두 달치 가상 거래입니다. 실제 상호/사업자번호가 아닙니다)")

        print("-" * 62)
        print("현재 잔액 (원장 합계):")
        report_balances(db)

    print("-" * 62)
    print("완료. 이제 서버를 띄우고 로그인하세요:")
    print("      uvicorn app.main:app --reload --port 8000")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
