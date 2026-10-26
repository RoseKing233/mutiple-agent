"""Development manager account bootstrap; never upgrades an existing customer."""

from __future__ import annotations

import uuid

import asyncpg
import bcrypt

MANAGER_EMAIL = "manager.demo@gmail.com"
MANAGER_PASSWORD = "manager123"


async def ensure_manager(
    conn: asyncpg.Connection,
    email: str = MANAGER_EMAIL,
    password: str = MANAGER_PASSWORD,
    name: str = "Store Manager",
) -> uuid.UUID:
    if len(password) < 8:
        raise ValueError("Manager password must contain at least 8 characters")
    row = await conn.fetchrow("SELECT id, role FROM users WHERE email=$1", email)
    if row and row["role"] != "store_manager":
        raise ValueError("Email belongs to a different role; existing accounts are never promoted automatically")
    if row:
        manager_id = row["id"]
    else:
        manager_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"ecommerce-manager:{email}")
        await conn.execute(
            """INSERT INTO users(id,email,password_hash,name,role)
               VALUES($1,$2,$3,$4,'store_manager')""",
            manager_id,
            email,
            bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
            name,
        )
    await conn.execute(
        """INSERT INTO agent_permissions(user_id,agent_name,role,granted_by)
           SELECT $1,name,'user',$1 FROM agent_catalog ON CONFLICT DO NOTHING""",
        manager_id,
    )
    return manager_id
