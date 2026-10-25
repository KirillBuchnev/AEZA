"""Собирает app/seeds/case_snapshot.json из датасета кейса в db/002_seed.sql.

Файл сида — источник истины. После его изменения запустите:
    python backend/scripts/build_case_snapshot.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "db" / "002_seed.sql"
OUT = ROOT / "backend" / "app" / "seeds" / "case_snapshot.json"
FIXTURE = re.compile(r"\$(fixture_\w+)\$(\[.*?\])\$\1\$", re.S)
REQUIRED = ("fixture_accounts", "fixture_services", "fixture_transactions")


def load_fixtures(text: str) -> dict[str, list[dict]]:
    found = {name: json.loads(body) for name, body in FIXTURE.findall(text)}
    missing = [name for name in REQUIRED if name not in found]
    if missing:
        raise SystemExit(f"{SEED.name} lacks {missing}")
    return found


def build(text: str) -> dict:
    fixtures = load_fixtures(text)
    owner_of: dict[int, int] = {}
    services_by_owner: dict[int, list[dict]] = {}
    for service in fixtures["fixture_services"]:
        owner_of[service["id"]] = service["ownerId"]
        services_by_owner.setdefault(service["ownerId"], []).append({
            "id": str(service["id"]),
            "name": service["name"],
            "price": service["price"],
            "autoprolong": service["autoProlong"],
            "paymentTerm": service["paymentTerm"],
            "status": service["status"],
            "expiresAt": service["expiresAt"],
        })
    transactions_by_owner: dict[int, list[dict]] = {}
    for transaction in fixtures["fixture_transactions"]:
        # Транзакция-сирота должна валить сборку, а не исчезать из снапшота.
        owner = owner_of[transaction["serviceId"]]
        transactions_by_owner.setdefault(owner, []).append({
            "id": str(transaction["id"]),
            "serviceId": str(transaction["serviceId"]),
            "status": transaction["status"],
            "type": transaction["type"],
            "amount": transaction["amount"],
            "createdAt": transaction.get("createdAt"),
        })
    customers = [
        {
            "id": str(account["id"]),
            "email": account["email"],
            "balance": account["balance"],
            "withdrawBalance": account["withdrawBalance"],
            "bonusBalance": account["bonusBalance"],
            "bonusState": account["bonusState"],
            "totalReplenished": account["totalReplenished"],
            "services": services_by_owner.get(account["id"], []),
            "transactions": transactions_by_owner.get(account["id"], []),
        }
        for account in fixtures["fixture_accounts"]
    ]
    return {"source": f"db/{SEED.name} (case dataset)", "customers": customers}


def main() -> None:
    data = build(SEED.read_text(encoding="utf-8"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    services = sum(len(customer["services"]) for customer in data["customers"])
    transactions = sum(len(customer["transactions"]) for customer in data["customers"])
    print(f"wrote {OUT}: {len(data['customers'])} customers, {services} services, {transactions} transactions")


if __name__ == "__main__":
    main()
