"""
YNAB → SQLite sync pipeline.

Pulls data from the YNAB API via YnabClient and upserts it into the local
SQLite database using the ORM. Writes a SyncLog row at the start (running)
and updates it at the end (success/failed).
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.budget import Budget, Category, CategoryGroup
from app.models.report import SyncLog
from app.models.transaction import Transaction
from app.services.ynab_client import YnabClient

logger = logging.getLogger(__name__)


async def run_sync(db: AsyncSession, api_key: str, budget_id: str) -> SyncLog:
    """
    Run a full delta sync: budget metadata, categories, accounts, transactions.

    Inserts a SyncLog row with status="running" at start and commits it
    immediately so it persists even if the sync later fails.  Updates to
    "success" or "failed" at the end.

    Args:
        db: Async SQLAlchemy session.
        api_key: Decrypted YNAB API key (do not log).
        budget_id: YNAB budget UUID to sync.

    Returns:
        The completed SyncLog row.

    Raises:
        Exception: Re-raises any exception after recording the failure.
    """
    now = datetime.now(timezone.utc).isoformat()
    sync_log = SyncLog(
        budget_id=None,  # Set after budget is confirmed to exist
        started_at=now,
        status="running",
    )
    db.add(sync_log)
    await db.commit()
    sync_log_id: int = sync_log.id  # Capture before any session reset

    try:
        client = YnabClient(api_key)

        # ----------------------------------------------------------------
        # Budget upsert
        # ----------------------------------------------------------------
        budgets_response = await client.get_budgets()
        budget_data = next(
            (b for b in budgets_response.budgets if b.id == budget_id), None
        )
        if budget_data is None:
            raise ValueError(f"Budget {budget_id!r} was not found in this YNAB account.")

        existing_budget = await db.get(Budget, budget_id)
        if existing_budget is None:
            currency_code = (
                budget_data.currency_format.get("iso_code")
                if isinstance(budget_data.currency_format, dict)
                else None
            )
            db.add(Budget(
                id=budget_data.id,
                name=budget_data.name,
                currency_format=currency_code,
                last_modified_on=budget_data.last_modified_on,
            ))
        else:
            existing_budget.name = budget_data.name
            existing_budget.last_modified_on = budget_data.last_modified_on

        await db.flush()

        # ----------------------------------------------------------------
        # Category groups + categories (full refresh — no delta for categories)
        # ----------------------------------------------------------------
        category_groups = await client.get_categories(budget_id)
        for group in category_groups:
            existing_group = await db.get(CategoryGroup, group.id)
            if existing_group is None:
                db.add(CategoryGroup(
                    id=group.id,
                    budget_id=budget_id,
                    name=group.name,
                    hidden=group.hidden,
                    deleted=group.deleted,
                ))
            else:
                existing_group.name = group.name
                existing_group.hidden = group.hidden
                existing_group.deleted = group.deleted

            for cat in group.categories:
                existing_cat = await db.get(Category, cat.id)
                if existing_cat is None:
                    db.add(Category(
                        id=cat.id,
                        group_id=cat.category_group_id,
                        budget_id=budget_id,
                        name=cat.name,
                        hidden=cat.hidden,
                        deleted=cat.deleted,
                        goal_type=cat.goal_type,
                        goal_target=cat.goal_target,
                        goal_percentage_complete=cat.goal_percentage_complete,
                    ))
                else:
                    existing_cat.name = cat.name
                    existing_cat.hidden = cat.hidden
                    existing_cat.deleted = cat.deleted
                    existing_cat.goal_type = cat.goal_type
                    existing_cat.goal_target = cat.goal_target
                    existing_cat.goal_percentage_complete = cat.goal_percentage_complete

        await db.flush()

        # ----------------------------------------------------------------
        # Accounts (full refresh — no delta for accounts)
        # ----------------------------------------------------------------
        accounts = await client.get_accounts(budget_id)
        for acct in accounts:
            existing_acct = await db.get(Account, acct.id)
            if existing_acct is None:
                db.add(Account(
                    id=acct.id,
                    budget_id=budget_id,
                    name=acct.name,
                    type=acct.type,
                    on_budget=acct.on_budget,
                    closed=acct.closed,
                    deleted=acct.deleted,
                    balance=acct.balance,
                    cleared_balance=acct.cleared_balance,
                    uncleared_balance=acct.uncleared_balance,
                ))
            else:
                existing_acct.name = acct.name
                existing_acct.type = acct.type
                existing_acct.on_budget = acct.on_budget
                existing_acct.closed = acct.closed
                existing_acct.deleted = acct.deleted
                existing_acct.balance = acct.balance
                existing_acct.cleared_balance = acct.cleared_balance
                existing_acct.uncleared_balance = acct.uncleared_balance

        await db.flush()

        # ----------------------------------------------------------------
        # Transactions — delta sync via last_knowledge_of_server
        # ----------------------------------------------------------------
        last_sync_result = await db.execute(
            select(SyncLog)
            .where(SyncLog.budget_id == budget_id, SyncLog.status == "success")
            .order_by(SyncLog.id.desc())
            .limit(1)
        )
        last_sync = last_sync_result.scalar_one_or_none()
        since_knowledge = last_sync.knowledge_of_server if last_sync else None

        txn_response = await client.get_transactions(budget_id, since_knowledge)

        # Pre-fetch existing IDs to distinguish adds vs updates without N+1 queries
        existing_ids_result = await db.execute(
            select(Transaction.id).where(Transaction.budget_id == budget_id)
        )
        existing_txn_ids: set[str] = {row[0] for row in existing_ids_result.fetchall()}

        transactions_added = 0
        transactions_updated = 0

        for txn in txn_response.transactions:
            if txn.id in existing_txn_ids:
                existing_txn = await db.get(Transaction, txn.id)
                if existing_txn is not None:
                    existing_txn.account_id = txn.account_id
                    existing_txn.category_id = txn.category_id
                    existing_txn.date = txn.date
                    existing_txn.amount = txn.amount
                    existing_txn.memo = txn.memo
                    existing_txn.payee_name = txn.payee_name
                    existing_txn.cleared = txn.cleared
                    existing_txn.approved = txn.approved
                    existing_txn.deleted = txn.deleted
                    transactions_updated += 1
            else:
                db.add(Transaction(
                    id=txn.id,
                    budget_id=budget_id,
                    account_id=txn.account_id,
                    category_id=txn.category_id,
                    date=txn.date,
                    amount=txn.amount,
                    memo=txn.memo,
                    payee_name=txn.payee_name,
                    cleared=txn.cleared,
                    approved=txn.approved,
                    deleted=txn.deleted,
                    import_id=txn.import_id,
                ))
                transactions_added += 1

        # ----------------------------------------------------------------
        # Finalise sync log
        # ----------------------------------------------------------------
        sync_log.budget_id = budget_id
        sync_log.finished_at = datetime.now(timezone.utc).isoformat()
        sync_log.status = "success"
        sync_log.transactions_added = transactions_added
        sync_log.transactions_updated = transactions_updated
        sync_log.knowledge_of_server = txn_response.server_knowledge

        await db.commit()
        logger.info(
            "Sync complete: +%d added, ~%d updated, server_knowledge=%d",
            transactions_added,
            transactions_updated,
            txn_response.server_knowledge,
        )
        return sync_log

    except Exception as exc:
        await db.rollback()
        # Re-fetch the SyncLog row (our initial commit is still intact)
        failed_log = await db.get(SyncLog, sync_log_id)
        if failed_log is not None:
            failed_log.finished_at = datetime.now(timezone.utc).isoformat()
            failed_log.status = "failed"
            failed_log.error_message = str(exc)[:1000]
            await db.commit()
        logger.error("Sync failed: %s", exc)
        raise
