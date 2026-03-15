"""
Async YNAB API v1 client.

Uses httpx.AsyncClient with delta sync via last_knowledge_of_server.
The YNAB API key is decrypted in memory and passed here — it must never
be logged or stored again after use.
"""

import httpx

from app.schemas.ynab import (
    YnabBudgetListResponse,
    YnabCategoryGroup,
    YnabAccount,
    YnabTransactionListResponse,
)

YNAB_BASE_URL = "https://api.ynab.com/v1"


class YnabClient:
    """Thin async wrapper around the YNAB REST API."""

    def __init__(self, api_key: str) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}

    async def get_budgets(self) -> YnabBudgetListResponse:
        """Fetch the list of budgets for this API key."""
        async with httpx.AsyncClient(headers=self._headers, timeout=30.0) as client:
            response = await client.get(f"{YNAB_BASE_URL}/budgets")
            response.raise_for_status()
            return YnabBudgetListResponse.model_validate(response.json()["data"])

    async def get_categories(self, budget_id: str) -> list[YnabCategoryGroup]:
        """Fetch all category groups and their categories for a budget."""
        async with httpx.AsyncClient(headers=self._headers, timeout=30.0) as client:
            response = await client.get(
                f"{YNAB_BASE_URL}/budgets/{budget_id}/categories"
            )
            response.raise_for_status()
            return [
                YnabCategoryGroup.model_validate(g)
                for g in response.json()["data"]["category_groups"]
            ]

    async def get_accounts(self, budget_id: str) -> list[YnabAccount]:
        """Fetch all accounts for a budget."""
        async with httpx.AsyncClient(headers=self._headers, timeout=30.0) as client:
            response = await client.get(
                f"{YNAB_BASE_URL}/budgets/{budget_id}/accounts"
            )
            response.raise_for_status()
            return [
                YnabAccount.model_validate(a)
                for a in response.json()["data"]["accounts"]
            ]

    async def get_transactions(
        self,
        budget_id: str,
        since_knowledge: int | None = None,
    ) -> YnabTransactionListResponse:
        """
        Fetch transactions using delta sync.
        Pass since_knowledge from the last successful sync to get only changes.
        """
        params: dict = {}
        if since_knowledge is not None:
            params["last_knowledge_of_server"] = since_knowledge

        async with httpx.AsyncClient(headers=self._headers, timeout=60.0) as client:
            response = await client.get(
                f"{YNAB_BASE_URL}/budgets/{budget_id}/transactions",
                params=params,
            )
            response.raise_for_status()
            return YnabTransactionListResponse.model_validate(response.json()["data"])
