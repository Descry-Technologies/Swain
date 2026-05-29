def search_users(db, tenant_id: str, query: str):
    sql = (
        f"select * from users where tenant_id = '{tenant_id}' "
        f"and email like '%{query}%'"
    )
    return db.execute(sql).fetchall()


def list_invoices(db, tenant_id: str):
    return db.execute(
        "select id, amount, status from invoices where tenant_id = :tenant_id",
        {"tenant_id": tenant_id},
    ).fetchall()
