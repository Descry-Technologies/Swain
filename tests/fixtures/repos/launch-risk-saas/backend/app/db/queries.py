def search_users(db, tenant_id: str, query: str):
    # Vulnerable fixture: user-controlled search string is interpolated into SQL.
    sql = (
        f"select * from users where tenant_id = '{tenant_id}' "
        f"and email like '%{query}%'"
    )
    return db.execute(sql).fetchall()


def list_invoices(db, tenant_id: str):
    # Vulnerable fixture: tenant_id argument is trusted by caller; tenant playbook
    # should ensure upstream routes bind it to the authenticated principal.
    return db.execute(
        "select id, amount, status from invoices where tenant_id = :tenant_id",
        {"tenant_id": tenant_id},
    ).fetchall()
