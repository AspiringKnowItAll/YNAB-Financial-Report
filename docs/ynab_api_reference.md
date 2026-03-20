# YNAB API — Authoritative Reference

**OpenAPI Version:** 3.1.1
**API Version:** 1.79.0
**Base URL:** `https://api.ynab.com/v1`
**Legacy Base URL:** `https://api.youneedabudget.com/v1` (still functional)
**Spec files:** `YNAB-api-1.json` / `YNAB-api-1.yaml`
**Source:** Merged from downloaded OpenAPI spec + live documentation at https://api.ynab.com

---

## Table of Contents

1. [Authentication](#1-authentication)
2. [Rate Limiting](#2-rate-limiting)
3. [Delta Requests (Incremental Sync)](#3-delta-requests-incremental-sync)
4. [Data Formats](#4-data-formats)
5. [Response Structure](#5-response-structure)
6. [Error Codes](#6-error-codes)
7. [Endpoint Quick Reference](#7-endpoint-quick-reference)
8. [Endpoints — User](#8-endpoints--user)
9. [Endpoints — Plans](#9-endpoints--plans)
10. [Endpoints — Accounts](#10-endpoints--accounts)
11. [Endpoints — Categories](#11-endpoints--categories)
12. [Endpoints — Payees](#12-endpoints--payees)
13. [Endpoints — Payee Locations](#13-endpoints--payee-locations)
14. [Endpoints — Months](#14-endpoints--months)
15. [Endpoints — Money Movements](#15-endpoints--money-movements)
16. [Endpoints — Transactions](#16-endpoints--transactions)
17. [Endpoints — Scheduled Transactions](#17-endpoints--scheduled-transactions)
18. [Schemas — Core & Plans](#18-schemas--core--plans)
19. [Schemas — Accounts](#19-schemas--accounts)
20. [Schemas — Categories](#20-schemas--categories)
21. [Schemas — Payees & Locations](#21-schemas--payees--locations)
22. [Schemas — Months](#22-schemas--months)
23. [Schemas — Money Movements](#23-schemas--money-movements)
24. [Schemas — Transactions](#24-schemas--transactions)
25. [Schemas — Scheduled Transactions](#25-schemas--scheduled-transactions)
26. [Enumerations](#26-enumerations)
27. [Project-Specific Notes](#27-project-specific-notes)
28. [Changelog](#28-changelog)
29. [Support & Resources](#29-support--resources)

---

## 1. Authentication

All requests require a Bearer token in the `Authorization` header.

```
Authorization: Bearer <ACCESS_TOKEN>
```

### 1.1 Personal Access Tokens

Self-generated tokens for personal use only.

- Created at: **Account Settings → Developer Settings** in the YNAB web app
- Never expire, but are revocable
- Cannot be retrieved after initial creation — store them securely
- Treat like a password; never share or commit to version control

**Example:**
```bash
curl -H "Authorization: Bearer <ACCESS_TOKEN>" https://api.ynab.com/v1/plans
```

### 1.2 OAuth Applications

For third-party integrations. Applications start in **Restricted Mode** (limited to 25 access tokens) and must apply for review (2–4 week process) to remove the restriction.

**Two grant types:**

| Grant Type | Use Case | Token Expiry | Refresh Tokens |
|---|---|---|---|
| Implicit Grant | Client-side apps where secret cannot be kept private | 2 hours | No |
| Authorization Code Grant | Server-side apps where secret can be stored securely | 2 hours | Yes |

**OAuth Security Parameters:**

| Parameter | Description |
|---|---|
| `scope=read-only` | Restricts to GET requests only. Write attempts return 403 `unauthorized_scope`. |
| `state` | CSRF protection. Same value is returned in the redirect — verify it matches. |
| `code_challenge` | PKCE support (RFC 7636) using SHA-256 hash of `code_verifier` (43–128 chars). |

**Default Plan Selection:**

When enabled during OAuth authorization, users select a default plan. Subsequent API calls may use `"default"` as the `plan_id` value in all endpoints.

**Legal Requirements for OAuth Apps:**
- Must comply with API Terms of Service and OAuth Requirements
- Must include a privacy policy disclosing data handling practices
- Must display "Works with YNAB" attribution if publicly available
- Must implement minimum-necessary permissions

---

## 2. Rate Limiting

**Limit:** 200 requests per hour per access token, enforced as a rolling window.

When exceeded, the API returns HTTP **429**:

```json
{
  "error": {
    "id": "429",
    "name": "too_many_requests",
    "detail": "Too many requests"
  }
}
```

> Note: The `X-Rate-Limit` header was removed in v1.73.0 — do not rely on it.

---

## 3. Delta Requests (Incremental Sync)

Many endpoints support incremental syncing to reduce bandwidth. When a response includes a `server_knowledge` integer, pass it back as the `last_knowledge_of_server` query parameter on the next request to receive **only entities that changed** since that point.

**Deleted entities** are only returned in delta responses (when `last_knowledge_of_server` is provided). They will have `deleted: true`.

**Endpoints that support `last_knowledge_of_server`:**

| Endpoint |
|---|
| `GET /plans/{plan_id}` |
| `GET /plans/{plan_id}/accounts` |
| `GET /plans/{plan_id}/categories` |
| `GET /plans/{plan_id}/months` |
| `GET /plans/{plan_id}/payees` |
| `GET /plans/{plan_id}/scheduled_transactions` |
| `GET /plans/{plan_id}/transactions` |
| `GET /plans/{plan_id}/accounts/{account_id}/transactions` |
| `GET /plans/{plan_id}/categories/{category_id}/transactions` |
| `GET /plans/{plan_id}/payees/{payee_id}/transactions` |
| `GET /plans/{plan_id}/months/{month}/transactions` |

> **Note on Money Movements:** The `MoneyMovementsResponse` and `MoneyMovementGroupsResponse` schemas both include a `server_knowledge` field in their responses, but the current spec does not declare `last_knowledge_of_server` as an accepted query parameter on those endpoints. The presence of `server_knowledge` in responses suggests future delta support may be added.

---

## 4. Data Formats

### 4.1 Currency — Milliunits

All monetary values are **integer milliunits** (amount × 1000). Never use floating-point dollars.

| Display | Milliunits |
|---|---|
| $123.93 | `123930` |
| €4,924.34 | `4924340` |
| -$0.22 | `-220` |
| $0.00 | `0` |

### 4.2 Dates

ISO 8601 / RFC 3339 `full-date`: `YYYY-MM-DD`

- All dates are **UTC**
- Month endpoints accept `"current"` to mean the current UTC calendar month

### 4.3 Timestamps

ISO 8601 datetime strings with UTC timezone (e.g. `2024-01-01T12:00:00Z`).

### 4.4 `plan_id` Special Values

| Value | Meaning |
|---|---|
| `"last-used"` | The most recently accessed plan |
| `"default"` | The plan selected during OAuth authorization (requires default plan selection to be enabled) |
| `{uuid}` | Direct plan UUID |

### 4.5 Null Handling

Response properties that have no value are returned as `null`, not omitted.

---

## 5. Response Structure

### Success

```json
{
  "data": {
    "plans": [{ "..." : "..." }],
    "server_knowledge": 12345
  }
}
```

### Error

```json
{
  "error": {
    "id": "404.2",
    "name": "resource_not_found",
    "detail": "The requested resource was not found"
  }
}
```

---

## 6. Error Codes

| HTTP Status | Error ID | Error Name | Description |
|---|---|---|---|
| 400 | 400 | `bad_request` | Malformed syntax or validation error |
| 401 | 401 | `not_authorized` | Token missing, invalid, revoked, or expired |
| 403 | 403.1 | `subscription_lapsed` | User's YNAB subscription has lapsed |
| 403 | 403.2 | `trial_expired` | User's trial period has expired |
| 403 | 403.3 | `unauthorized_scope` | Token scope insufficient (e.g., read-only token on a write endpoint) |
| 403 | 403.4 | `data_limit_reached` | Request would exceed data limits |
| 404 | 404.1 | `not_found` | The URI does not exist |
| 404 | 404.2 | `resource_not_found` | The requested resource was not found |
| 409 | 409 | `conflict` | Resource conflicts with an existing one (e.g., duplicate `import_id`) |
| 429 | 429 | `too_many_requests` | Rate limit exceeded (200/hr rolling window) |
| 500 | 500 | `internal_server_error` | Unexpected API error |
| 503 | 503 | `service_unavailable` | Temporary access disabled or request timeout (>30 seconds) |

---

## 7. Endpoint Quick Reference

| Method | Path | Operation ID | Description |
|---|---|---|---|
| GET | `/user` | `getUser` | Get authenticated user |
| GET | `/plans` | `getPlans` | List all plans |
| GET | `/plans/{plan_id}` | `getPlanById` | Full plan export |
| GET | `/plans/{plan_id}/settings` | `getPlanSettingsById` | Plan date/currency settings |
| GET | `/plans/{plan_id}/accounts` | `getAccounts` | List all accounts |
| POST | `/plans/{plan_id}/accounts` | `createAccount` | Create an account |
| GET | `/plans/{plan_id}/accounts/{account_id}` | `getAccountById` | Get single account |
| GET | `/plans/{plan_id}/categories` | `getCategories` | List all categories (grouped) |
| POST | `/plans/{plan_id}/categories` | `createCategory` | Create a category |
| GET | `/plans/{plan_id}/categories/{category_id}` | `getCategoryById` | Get single category |
| PATCH | `/plans/{plan_id}/categories/{category_id}` | `updateCategory` | Update a category |
| GET | `/plans/{plan_id}/months/{month}/categories/{category_id}` | `getMonthCategoryById` | Get category for specific month |
| PATCH | `/plans/{plan_id}/months/{month}/categories/{category_id}` | `updateMonthCategory` | Update budgeted amount for month |
| POST | `/plans/{plan_id}/category_groups` | `createCategoryGroup` | Create a category group |
| PATCH | `/plans/{plan_id}/category_groups/{category_group_id}` | `updateCategoryGroup` | Update a category group |
| GET | `/plans/{plan_id}/payees` | `getPayees` | List all payees |
| GET | `/plans/{plan_id}/payees/{payee_id}` | `getPayeeById` | Get single payee |
| PATCH | `/plans/{plan_id}/payees/{payee_id}` | `updatePayee` | Update a payee |
| GET | `/plans/{plan_id}/payee_locations` | `getPayeeLocations` | List all payee locations |
| GET | `/plans/{plan_id}/payee_locations/{payee_location_id}` | `getPayeeLocationById` | Get single payee location |
| GET | `/plans/{plan_id}/payees/{payee_id}/payee_locations` | `getPayeeLocationsByPayee` | Locations for a payee |
| GET | `/plans/{plan_id}/months` | `getPlanMonths` | List all plan months |
| GET | `/plans/{plan_id}/months/{month}` | `getPlanMonth` | Get single month detail |
| GET | `/plans/{plan_id}/money_movements` | `getMoneyMovements` | List all money movements |
| GET | `/plans/{plan_id}/months/{month}/money_movements` | `getMoneyMovementsByMonth` | Money movements for a month |
| GET | `/plans/{plan_id}/money_movement_groups` | `getMoneyMovementGroups` | List all money movement groups |
| GET | `/plans/{plan_id}/months/{month}/money_movement_groups` | `getMoneyMovementGroupsByMonth` | Movement groups for a month |
| GET | `/plans/{plan_id}/transactions` | `getTransactions` | List all transactions |
| POST | `/plans/{plan_id}/transactions` | `createTransaction` | Create single or bulk transactions |
| PATCH | `/plans/{plan_id}/transactions` | `updateTransactions` | Bulk update transactions |
| POST | `/plans/{plan_id}/transactions/import` | `importTransactions` | Trigger direct import |
| GET | `/plans/{plan_id}/transactions/{transaction_id}` | `getTransactionById` | Get single transaction |
| PUT | `/plans/{plan_id}/transactions/{transaction_id}` | `updateTransaction` | Update single transaction |
| DELETE | `/plans/{plan_id}/transactions/{transaction_id}` | `deleteTransaction` | Delete a transaction |
| GET | `/plans/{plan_id}/accounts/{account_id}/transactions` | `getTransactionsByAccount` | Transactions by account |
| GET | `/plans/{plan_id}/categories/{category_id}/transactions` | `getTransactionsByCategory` | Transactions by category |
| GET | `/plans/{plan_id}/payees/{payee_id}/transactions` | `getTransactionsByPayee` | Transactions by payee |
| GET | `/plans/{plan_id}/months/{month}/transactions` | `getTransactionsByMonth` | Transactions by month |
| GET | `/plans/{plan_id}/scheduled_transactions` | `getScheduledTransactions` | List all scheduled transactions |
| POST | `/plans/{plan_id}/scheduled_transactions` | `createScheduledTransaction` | Create a scheduled transaction |
| GET | `/plans/{plan_id}/scheduled_transactions/{scheduled_transaction_id}` | `getScheduledTransactionById` | Get single scheduled transaction |
| PUT | `/plans/{plan_id}/scheduled_transactions/{scheduled_transaction_id}` | `updateScheduledTransaction` | Update scheduled transaction |
| DELETE | `/plans/{plan_id}/scheduled_transactions/{scheduled_transaction_id}` | `deleteScheduledTransaction` | Delete scheduled transaction |

---

## 8. Endpoints — User

### `GET /user`

Returns authenticated user information.

**Parameters:** None
**Response 200** — `UserResponse`:
```
data.user.id  (string, uuid)
```

---

## 9. Endpoints — Plans

> **v1.79.0 Migration Note:** All endpoints use `/plans/{plan_id}`. The legacy `/budgets/{budget_id}` paths remain functional and return original JSON key names (`budget`, `budgets`, `default_budget`).

### `GET /plans`

Returns list of all plans with summary information.

**Query Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `include_accounts` | boolean | No | Whether to include the list of plan accounts in each `PlanSummary` |

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `PlanSummaryResponse` | The list of plans |
| 404 | `ErrorResponse` | No plans were found |

---

### `GET /plans/{plan_id}`

Returns a single plan with **all related entities**. This is effectively a full plan export.

**Path Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `plan_id` | string | Yes | Plan UUID, `"last-used"`, or `"default"` |

**Query Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `last_knowledge_of_server` | int64 | No | If provided, only entities changed since this value are included |

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `PlanDetailResponse` | The requested plan with `server_knowledge` |
| 404 | `ErrorResponse` | The specified plan was not found |

---

### `GET /plans/{plan_id}/settings`

Returns date and currency format settings for a plan.

**Path Parameters:** `plan_id` (string, required)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `PlanSettingsResponse` | The requested plan settings |
| 404 | `ErrorResponse` | The specified plan was not found |

---

## 10. Endpoints — Accounts

### `GET /plans/{plan_id}/accounts`

Returns all accounts. Supports delta requests.

**Path Parameters:** `plan_id` (string, required)
**Query Parameters:** `last_knowledge_of_server` (int64, optional)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `AccountsResponse` | List of accounts with `server_knowledge` |
| 404 | `ErrorResponse` | No accounts were found |

---

### `POST /plans/{plan_id}/accounts`

Creates a new account.

**Path Parameters:** `plan_id` (string, required)

**Request Body** (required) — `PostAccountWrapper`:

```json
{
  "account": {
    "name": "Checking Account",
    "type": "checking",
    "balance": 100000
  }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | Yes | Account name |
| `type` | AccountType | Yes | See AccountType enum |
| `balance` | int64 | Yes | Initial balance in milliunits |

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 201 | `AccountResponse` | The account was successfully created |
| 400 | `ErrorResponse` | Malformed syntax or validation error |

---

### `GET /plans/{plan_id}/accounts/{account_id}`

Returns a single account.

**Path Parameters:** `plan_id` (string, required), `account_id` (uuid, required)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `AccountResponse` | The requested account |
| 404 | `ErrorResponse` | The requested account was not found |

---

## 11. Endpoints — Categories

Category amounts (`budgeted`, `activity`, `balance`) are always specific to the **current plan month (UTC)** unless requesting via a month-specific endpoint.

### `GET /plans/{plan_id}/categories`

Returns all categories grouped by category group.

**Path Parameters:** `plan_id` (string, required)
**Query Parameters:** `last_knowledge_of_server` (int64, optional)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `CategoriesResponse` | Categories grouped with `server_knowledge` |
| 404 | `ErrorResponse` | No categories were found |

---

### `POST /plans/{plan_id}/categories`

Creates a new category.

**Path Parameters:** `plan_id` (string, required)

**Request Body** (required) — `PostCategoryWrapper` → `NewCategory`:

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | Yes | Category name |
| `category_group_id` | uuid | Yes | Parent category group |
| `note` | string, nullable | No | |
| `goal_target` | int64, nullable | No | If set and no goal exists, creates a monthly NEED goal with this target |
| `goal_target_date` | date, nullable | No | ISO format (e.g. `2016-12-01`) |

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 201 | `SaveCategoryResponse` | Category created; includes `server_knowledge` |
| 400 | `ErrorResponse` | Validation error |

---

### `GET /plans/{plan_id}/categories/{category_id}`

Returns a single category. Amounts are current-month specific.

**Path Parameters:** `plan_id` (string, required), `category_id` (string, required)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `CategoryResponse` | The requested category |
| 404 | `ErrorResponse` | The category was not found |

---

### `PATCH /plans/{plan_id}/categories/{category_id}`

Updates a category.

**Path Parameters:** `plan_id` (string, required), `category_id` (string, required)

**Request Body** (required) — `PatchCategoryWrapper` → `ExistingCategory` (all `SaveCategory` fields optional):

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string, nullable | No | |
| `note` | string, nullable | No | |
| `category_group_id` | uuid | No | |
| `goal_target` | int64, nullable | No | |
| `goal_target_date` | date, nullable | No | |

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `SaveCategoryResponse` | Category updated; includes `server_knowledge` |
| 400 | `ErrorResponse` | Validation error |

---

### `GET /plans/{plan_id}/months/{month}/categories/{category_id}`

Returns a single category for a specific plan month.

**Path Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `plan_id` | string | Yes | |
| `month` | date | Yes | ISO format (e.g. `2016-12-01`) or `"current"` (UTC) |
| `category_id` | string | Yes | |

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `CategoryResponse` | The requested month category |
| 404 | `ErrorResponse` | The month category was not found |

---

### `PATCH /plans/{plan_id}/months/{month}/categories/{category_id}`

Updates a category for a specific month. **Only the `budgeted` (assigned) amount can be updated. All other fields are ignored.**

**Path Parameters:** same as GET above

**Request Body** (required) — `PatchMonthCategoryWrapper` → `SaveMonthCategory`:

| Field | Type | Required | Description |
|---|---|---|---|
| `budgeted` | int64 | Yes | Assigned amount in milliunits |

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `SaveCategoryResponse` | Category updated; includes `server_knowledge` |
| 400 | `ErrorResponse` | Validation error |

---

### `POST /plans/{plan_id}/category_groups`

Creates a new category group.

**Path Parameters:** `plan_id` (string, required)

**Request Body** (required) — `PostCategoryGroupWrapper` → `SaveCategoryGroup`:

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | Yes | Maximum 50 characters |

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 201 | `SaveCategoryGroupResponse` | Group created; includes `server_knowledge` |
| 400 | `ErrorResponse` | Validation error |

---

### `PATCH /plans/{plan_id}/category_groups/{category_group_id}`

Updates a category group.

**Path Parameters:** `plan_id` (string, required), `category_group_id` (string, required)

**Request Body** (required) — `PatchCategoryGroupWrapper` → `SaveCategoryGroup`:

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | Yes | Maximum 50 characters |

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `SaveCategoryGroupResponse` | Group updated; includes `server_knowledge` |
| 400 | `ErrorResponse` | Validation error |

---

## 12. Endpoints — Payees

### `GET /plans/{plan_id}/payees`

Returns all payees. Supports delta requests.

**Path Parameters:** `plan_id` (string, required)
**Query Parameters:** `last_knowledge_of_server` (int64, optional)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `PayeesResponse` | Payees list with `server_knowledge` |
| 404 | `ErrorResponse` | No payees were found |

---

### `GET /plans/{plan_id}/payees/{payee_id}`

Returns a single payee.

**Path Parameters:** `plan_id` (string, required), `payee_id` (string, required)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `PayeeResponse` | The requested payee |
| 404 | `ErrorResponse` | The payee was not found |

---

### `PATCH /plans/{plan_id}/payees/{payee_id}`

Updates a payee (e.g., rename it).

**Path Parameters:** `plan_id` (string, required), `payee_id` (string, required)

**Request Body** (required) — `PatchPayeeWrapper` → `SavePayee`:

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | No | Maximum 500 characters; not nullable |

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `SavePayeeResponse` | Payee updated; includes `server_knowledge` |
| 400 | `ErrorResponse` | Validation error |

---

## 13. Endpoints — Payee Locations

GPS coordinates stored when a transaction is entered on the YNAB mobile app (with user permission). Not available for all payees.

### `GET /plans/{plan_id}/payee_locations`

Returns all payee locations.

**Path Parameters:** `plan_id` (string, required)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `PayeeLocationsResponse` | List of payee locations |
| 404 | `ErrorResponse` | No payee locations were found |

---

### `GET /plans/{plan_id}/payee_locations/{payee_location_id}`

Returns a single payee location.

**Path Parameters:** `plan_id` (string, required), `payee_location_id` (string, required)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `PayeeLocationResponse` | The payee location |
| 404 | `ErrorResponse` | The payee location was not found |

---

### `GET /plans/{plan_id}/payees/{payee_id}/payee_locations`

Returns all locations for a specific payee.

**Path Parameters:** `plan_id` (string, required), `payee_id` (string, required)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `PayeeLocationsResponse` | List of locations for that payee |
| 404 | `ErrorResponse` | No payee locations were found |

---

## 14. Endpoints — Months

Each plan month contains Ready to Assign, Age of Money, and per-category amounts.

### `GET /plans/{plan_id}/months`

Returns all plan months (summaries). Supports delta requests.

**Path Parameters:** `plan_id` (string, required)
**Query Parameters:** `last_knowledge_of_server` (int64, optional)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `MonthSummariesResponse` | Months list with `server_knowledge` |
| 404 | `ErrorResponse` | No plan months were found |

---

### `GET /plans/{plan_id}/months/{month}`

Returns a single plan month with full detail including all categories.

**Path Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `plan_id` | string | Yes | |
| `month` | date | Yes | ISO format (e.g. `2016-12-01`) or `"current"` (UTC) |

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `MonthDetailResponse` | The plan month detail (no `server_knowledge` in this response) |
| 404 | `ErrorResponse` | The plan month was not found |

---

## 15. Endpoints — Money Movements

### `GET /plans/{plan_id}/money_movements`

Returns all money movements for a plan.

**Path Parameters:** `plan_id` (string, required)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `MoneyMovementsResponse` | Money movements list with `server_knowledge` |
| 404 | `ErrorResponse` | No money movements were found |

---

### `GET /plans/{plan_id}/months/{month}/money_movements`

Returns all money movements for a specific month.

**Path Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `plan_id` | string | Yes | |
| `month` | date | Yes | ISO format (e.g. `2016-12-01`) or `"current"` (UTC) |

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `MoneyMovementsResponse` | Money movements for the month |
| 404 | `ErrorResponse` | No money movements were found |

---

### `GET /plans/{plan_id}/money_movement_groups`

Returns all money movement groups for a plan.

**Path Parameters:** `plan_id` (string, required)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `MoneyMovementGroupsResponse` | Groups list with `server_knowledge` |
| 404 | `ErrorResponse` | No money movement groups were found |

---

### `GET /plans/{plan_id}/months/{month}/money_movement_groups`

Returns all money movement groups for a specific month.

**Path Parameters:** `plan_id` (string, required), `month` (date, required)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `MoneyMovementGroupsResponse` | Groups for the month |
| 404 | `ErrorResponse` | No money movement groups were found |

---

## 16. Endpoints — Transactions

> **Important:** All transaction endpoints **exclude pending transactions**.

### `GET /plans/{plan_id}/transactions`

Returns all plan transactions. Supports delta requests.

**Path Parameters:** `plan_id` (string, required)

**Query Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `since_date` | date | No | Only transactions on or after this date (ISO format, e.g. `2016-12-30`) |
| `type` | string | No | Filter: `"uncategorized"` or `"unapproved"` |
| `last_knowledge_of_server` | int64 | No | Delta request filter |

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `TransactionsResponse` | Transactions list with `server_knowledge` |
| 400 | `ErrorResponse` | An error occurred |
| 404 | `ErrorResponse` | No transactions were found |

---

### `POST /plans/{plan_id}/transactions`

Creates a single transaction **or** multiple transactions. Submit either `transaction` (single) or `transactions` (array) — not both. **Scheduled transactions (future dates) cannot be created via this endpoint.**

**Path Parameters:** `plan_id` (string, required)

**Request Body** (required) — `PostTransactionsWrapper`:

```json
{
  "transaction": { ... }
}
```
OR
```json
{
  "transactions": [{ ... }, { ... }]
}
```

**`NewTransaction` fields** (extends `SaveTransactionWithOptionalFields`):

| Field | Type | Required | Description |
|---|---|---|---|
| `account_id` | uuid | No | Account for the transaction |
| `date` | date | No | ISO format. Future dates (scheduled) are not permitted. Split transaction dates cannot be changed. |
| `amount` | int64 | No | Amount in milliunits. Split transaction amounts cannot be changed. |
| `payee_id` | uuid, nullable | No | Payee. To transfer, use the target account's `transfer_payee_id`. |
| `payee_name` | string (max 200), nullable | No | If `payee_id` is null: resolves by (1) payee rename rule (if `import_id` also set), (2) matching name, or (3) creates new payee. |
| `category_id` | uuid, nullable | No | Category. Set to `null` with `subtransactions` for split. Cannot change if already a split. Credit Card Payment categories ignored. |
| `memo` | string (max 500), nullable | No | |
| `cleared` | TransactionClearedStatus | No | `cleared`, `uncleared`, or `reconciled` |
| `approved` | boolean | No | Defaults to `false` if not supplied |
| `flag_color` | TransactionFlagColor, nullable | No | See TransactionFlagColor enum |
| `subtransactions` | SaveSubTransaction[] | No | For split transactions. Updating subtransactions on existing split is not supported. |
| `import_id` | string (max 36), nullable | No | See import_id rules below |

**`import_id` rules:**
- If specified, transaction is treated as "imported"
- YNAB will attempt to match it against existing "user-entered" transactions on the same account, same amount, date ±10 days
- If `import_id` is null or omitted, treated as "user-entered" (eligible for future import matching)
- Recommended format: `YNAB:[milliunit_amount]:[iso_date]:[occurrence]`
- Example: `-$294.23 on 2015-12-30` → `YNAB:-294230:2015-12-30:1` (second occurrence → `:2`)
- Must be unique per account; conflicts return HTTP 409

**`SaveSubTransaction` fields:**

| Field | Type | Required | Description |
|---|---|---|---|
| `amount` | int64 | Yes | Amount in milliunits |
| `payee_id` | uuid, nullable | No | |
| `payee_name` | string (max 200), nullable | No | Resolves by (1) rename rule (if parent has `import_id`), (2) match, (3) create |
| `category_id` | uuid, nullable | No | Credit Card Payment categories ignored |
| `memo` | string (max 500), nullable | No | |

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 201 | `SaveTransactionsResponse` | Transaction(s) successfully created |
| 400 | `ErrorResponse` | Validation error |
| 409 | `ErrorResponse` | `import_id` already exists on the same account |

---

### `PATCH /plans/{plan_id}/transactions`

Updates multiple transactions by `id` or `import_id`.

**Path Parameters:** `plan_id` (string, required)

**Request Body** (required) — `PatchTransactionsWrapper`:

```json
{
  "transactions": [
    { "id": "abc123", "approved": true },
    { "import_id": "YNAB:-5000:2024-01-15:1", "memo": "Updated" }
  ]
}
```

**`SaveTransactionWithIdOrImportId` fields:**

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string, nullable | No | If specified, used to look up by `id`. Takes priority over `import_id`. |
| `import_id` | string (max 36), nullable | No | Used to look up by `import_id` if `id` is null. Cannot update an `import_id` on an existing transaction. |
| *(all SaveTransactionWithOptionalFields fields)* | | | |

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 209 | `SaveTransactionsResponse` | Transactions successfully updated |
| 400 | `ErrorResponse` | Validation error |

---

### `POST /plans/{plan_id}/transactions/import`

Initiates import of available transactions from all **linked** (direct import) accounts. Equivalent to clicking "Import" on each linked account in the web app or tapping "New Transactions" on mobile.

**Path Parameters:** `plan_id` (string, required)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `TransactionsImportResponse` | Request successful but no new transactions to import |
| 201 | `TransactionsImportResponse` | One or more transactions were imported |
| 400 | `ErrorResponse` | Validation error |

---

### `GET /plans/{plan_id}/transactions/{transaction_id}`

Returns a single transaction.

**Path Parameters:** `plan_id` (string, required), `transaction_id` (string, required)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `TransactionResponse` | The requested transaction with `server_knowledge` |
| 404 | `ErrorResponse` | The transaction was not found |

---

### `PUT /plans/{plan_id}/transactions/{transaction_id}`

Updates a single transaction (full replace of mutable fields).

**Path Parameters:** `plan_id` (string, required), `transaction_id` (string, required)

**Request Body** (required) — `PutTransactionWrapper`:
```json
{
  "transaction": { ... }
}
```
Uses `ExistingTransaction` (all `SaveTransactionWithOptionalFields` fields, all optional).

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `TransactionResponse` | Transaction successfully updated |
| 400 | `ErrorResponse` | Validation error |

---

### `DELETE /plans/{plan_id}/transactions/{transaction_id}`

Deletes a transaction.

**Path Parameters:** `plan_id` (string, required), `transaction_id` (string, required)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `TransactionResponse` | Transaction successfully deleted (returns deleted transaction) |
| 404 | `ErrorResponse` | The transaction was not found |

---

### `GET /plans/{plan_id}/accounts/{account_id}/transactions`

Returns all transactions for a specific account.

**Path Parameters:** `plan_id` (string, required), `account_id` (string, required)
**Query Parameters:** `since_date` (date, optional), `type` (string, optional), `last_knowledge_of_server` (int64, optional)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `TransactionsResponse` | Transactions with `server_knowledge` |
| 404 | `ErrorResponse` | No transactions were found |

---

### `GET /plans/{plan_id}/categories/{category_id}/transactions`

Returns all transactions for a specific category. Returns `HybridTransaction` (includes subtransactions as flat rows).

**Path Parameters:** `plan_id` (string, required), `category_id` (string, required)
**Query Parameters:** `since_date` (date, optional), `type` (string, optional), `last_knowledge_of_server` (int64, optional)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `HybridTransactionsResponse` | Hybrid transactions (server_knowledge optional) |
| 404 | `ErrorResponse` | No transactions were found |

---

### `GET /plans/{plan_id}/payees/{payee_id}/transactions`

Returns all transactions for a specific payee. Returns `HybridTransaction`.

**Path Parameters:** `plan_id` (string, required), `payee_id` (string, required)
**Query Parameters:** `since_date` (date, optional), `type` (string, optional), `last_knowledge_of_server` (int64, optional)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `HybridTransactionsResponse` | Hybrid transactions |
| 404 | `ErrorResponse` | No transactions were found |

---

### `GET /plans/{plan_id}/months/{month}/transactions`

Returns all transactions for a specific month.

**Path Parameters:** `plan_id` (string, required), `month` (string, required — ISO date or `"current"`)
**Query Parameters:** `since_date` (date, optional), `type` (string, optional), `last_knowledge_of_server` (int64, optional)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `TransactionsResponse` | Transactions with `server_knowledge` |
| 404 | `ErrorResponse` | No transactions were found |

---

## 17. Endpoints — Scheduled Transactions

### `GET /plans/{plan_id}/scheduled_transactions`

Returns all scheduled transactions. Supports delta requests.

**Path Parameters:** `plan_id` (string, required)
**Query Parameters:** `last_knowledge_of_server` (int64, optional)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `ScheduledTransactionsResponse` | Scheduled transactions (as `ScheduledTransactionDetail`) with `server_knowledge` |
| 404 | `ErrorResponse` | No scheduled transactions were found |

---

### `POST /plans/{plan_id}/scheduled_transactions`

Creates a single scheduled transaction (a transaction with a future date).

**Path Parameters:** `plan_id` (string, required)

**Request Body** (required) — `PostScheduledTransactionWrapper` → `SaveScheduledTransaction`:

| Field | Type | Required | Description |
|---|---|---|---|
| `account_id` | uuid | Yes | Account for the transaction |
| `date` | date | Yes | Future date in ISO format. Must not be more than 5 years in the future. |
| `amount` | int64 | No | Amount in milliunits |
| `payee_id` | uuid, nullable | No | Payee. Use `transfer_payee_id` for transfers. |
| `payee_name` | string (max 200), nullable | No | Resolves by (1) matching name, or (2) creates new payee |
| `category_id` | uuid, nullable | No | Category. Credit Card Payment categories not permitted. Split scheduled transactions not currently supported. |
| `memo` | string (max 500), nullable | No | |
| `flag_color` | TransactionFlagColor, nullable | No | |
| `frequency` | ScheduledTransactionFrequency | No | See frequency enum |

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 201 | `ScheduledTransactionResponse` | Scheduled transaction created |
| 400 | `ErrorResponse` | Validation error |

---

### `GET /plans/{plan_id}/scheduled_transactions/{scheduled_transaction_id}`

Returns a single scheduled transaction.

**Path Parameters:** `plan_id` (string, required), `scheduled_transaction_id` (string, required)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `ScheduledTransactionResponse` | The requested scheduled transaction |
| 404 | `ErrorResponse` | The scheduled transaction was not found |

---

### `PUT /plans/{plan_id}/scheduled_transactions/{scheduled_transaction_id}`

Updates a single scheduled transaction.

**Path Parameters:** `plan_id` (string, required), `scheduled_transaction_id` (string, required)

**Request Body** (required) — `PutScheduledTransactionWrapper` → `SaveScheduledTransaction` (same fields as POST)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `ScheduledTransactionResponse` | Scheduled transaction updated |
| 400 | `ErrorResponse` | Validation error |

---

### `DELETE /plans/{plan_id}/scheduled_transactions/{scheduled_transaction_id}`

Deletes a scheduled transaction.

**Path Parameters:** `plan_id` (string, required), `scheduled_transaction_id` (string, required)

**Responses:**

| Status | Schema | Description |
|---|---|---|
| 200 | `ScheduledTransactionResponse` | Successfully deleted (returns deleted transaction) |
| 404 | `ErrorResponse` | The scheduled transaction was not found |

---

## 18. Schemas — Core & Plans

### `ErrorResponse`
```
error  (ErrorDetail, required)
```

### `ErrorDetail`
```
id      (string, required)  — error identifier
name    (string, required)  — error name
detail  (string, required)  — human-readable description
```

### `User`
```
id  (uuid, required)
```

### `UserResponse`
```
data.user  (User, required)
```

### `PlanSummary`

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | uuid | Yes | Plan identifier |
| `name` | string | Yes | Plan name |
| `last_modified_on` | datetime | No | Last time any changes were made from web or mobile |
| `first_month` | date | No | The earliest plan month |
| `last_month` | date | No | The latest plan month |
| `date_format` | DateFormat, nullable | No | Date format (null if unavailable) |
| `currency_format` | CurrencyFormat, nullable | No | Currency format (null if unavailable) |
| `accounts` | Account[] | No | Only included if `include_accounts=true` |

### `PlanSummaryResponse`
```
data.plans[]        (PlanSummary array, required)
data.default_plan   (PlanSummary, nullable)  — only if default plan enabled
```

### `PlanDetail`
Extends `PlanSummary`, adding:
```
accounts[]                  (Account[])
payees[]                    (Payee[])
payee_locations[]           (PayeeLocation[])
category_groups[]           (CategoryGroup[])
categories[]                (Category[])
months[]                    (MonthDetail[])
transactions[]              (TransactionSummary[])
subtransactions[]           (SubTransaction[])
scheduled_transactions[]    (ScheduledTransactionSummary[])
scheduled_subtransactions[] (ScheduledSubTransaction[])
```

### `PlanDetailResponse`
```
data.plan             (PlanDetail, required)
data.server_knowledge (int64, required)
```

### `PlanSettings`
```
date_format      (DateFormat, required)
currency_format  (CurrencyFormat, required)
```

### `PlanSettingsResponse`
```
data.settings  (PlanSettings, required)
```

### `DateFormat`
```
format  (string, required)
```
Type is `[object, null]` — may be null if the format is unavailable for the plan.

### `CurrencyFormat`

| Field | Type | Required | Description |
|---|---|---|---|
| `iso_code` | string | Yes | ISO currency code (e.g. `"USD"`) |
| `example_format` | string | Yes | Example of the formatted currency (e.g. `"123,456.78"`) |
| `decimal_digits` | int32 | Yes | Number of decimal places |
| `decimal_separator` | string | Yes | Decimal separator character |
| `symbol_first` | boolean | Yes | Whether symbol appears before amount |
| `group_separator` | string | Yes | Thousands separator character |
| `currency_symbol` | string | Yes | Currency symbol character |
| `display_symbol` | boolean | Yes | Whether to display the symbol |

Type is `[object, null]` — may be null if the format is unavailable for the plan.

---

## 19. Schemas — Accounts

### `Account`

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | uuid | Yes | |
| `name` | string | Yes | |
| `type` | AccountType | Yes | See AccountType enum |
| `on_budget` | boolean | Yes | Whether this account is "on budget" |
| `closed` | boolean | Yes | Whether this account is closed |
| `note` | string, nullable | No | |
| `balance` | int64 | Yes | Current available balance in milliunits |
| `cleared_balance` | int64 | Yes | Cleared balance in milliunits |
| `uncleared_balance` | int64 | Yes | Uncleared balance in milliunits |
| `transfer_payee_id` | uuid, nullable | Yes | The payee id to use when transferring **to** this account |
| `direct_import_linked` | boolean | No | Whether linked to a financial institution for auto-import |
| `direct_import_in_error` | boolean | No | If linked (`direct_import_linked=true`) and connection is unhealthy, this is `true` |
| `last_reconciled_at` | datetime, nullable | No | When the account was last reconciled |
| `debt_original_balance` | int64, nullable | No | **Deprecated** — always returns null |
| `debt_interest_rates` | LoanAccountPeriodicValue, nullable | No | Key-value map of effective dates → interest rates |
| `debt_minimum_payments` | LoanAccountPeriodicValue, nullable | No | Key-value map of effective dates → minimum payments |
| `debt_escrow_amounts` | LoanAccountPeriodicValue, nullable | No | Key-value map of effective dates → escrow amounts |
| `deleted` | boolean | Yes | Deleted accounts only included in delta requests |

### `SaveAccount`
```
name     (string, required)
type     (AccountType, required)
balance  (int64, required)  — initial balance in milliunits
```

### `PostAccountWrapper`
```
account  (SaveAccount, required)
```

### `AccountsResponse`
```
data.accounts[]       (Account[], required)
data.server_knowledge (int64, required)
```

### `AccountResponse`
```
data.account  (Account, required)
```

### `LoanAccountPeriodicValue`

A map of `{ "YYYY-MM-DD": int64 }` where each key is the effective date and the value is the periodic amount in milliunits. Type is `[object, null]`.

---

## 20. Schemas — Categories

### `CategoryGroup`

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | uuid | Yes | |
| `name` | string | Yes | |
| `hidden` | boolean | Yes | Whether the category group is hidden |
| `deleted` | boolean | Yes | Deleted groups only included in delta requests |

### `CategoryGroupWithCategories`

Extends `CategoryGroup`, adding:
```
categories[]  (Category[], required)  — amounts are current-month specific (UTC)
```

### `Category`

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | uuid | Yes | |
| `category_group_id` | uuid | Yes | Parent group |
| `category_group_name` | string | No | Parent group name |
| `name` | string | Yes | |
| `hidden` | boolean | Yes | Whether the category is hidden |
| `original_category_group_id` | uuid, nullable | No | **Deprecated** — always null |
| `note` | string, nullable | No | |
| `budgeted` | int64 | Yes | Assigned amount in milliunits (current month) |
| `activity` | int64 | Yes | Activity amount in milliunits (current month) |
| `balance` | int64 | Yes | Available balance in milliunits (current month) |
| `goal_type` | string, nullable | No | `TB`, `TBD`, `MF`, `NEED`, `DEBT`, or null |
| `goal_needs_whole_amount` | boolean, nullable | No | For NEED goals: `true` = "Set Aside" (always ask for full target), `false` = "Refill" (use prior month funding). Null for other goal types. Default: null |
| `goal_day` | int32, nullable | No | For `goal_cadence=2` (weekly): 0=Sunday through 6=Saturday. Otherwise: day of month (1–31, null=last day) |
| `goal_cadence` | int32 (0–14), nullable | No | See goal cadence table below |
| `goal_cadence_frequency` | int32, nullable | No | Multiplier for cadences 0/1/2/13. Ignored for cadences 3–12 and 14. |
| `goal_creation_month` | date, nullable | No | Month the goal was created |
| `goal_target` | int64, nullable | No | Goal target amount in milliunits |
| `goal_target_month` | date, nullable | No | **Deprecated** — use `goal_target_date` |
| `goal_target_date` | date, nullable | No | Target date for goal completion |
| `goal_percentage_complete` | int32, nullable | No | Percentage toward completion |
| `goal_months_to_budget` | int32, nullable | No | Months remaining (including current month) in current goal period |
| `goal_under_funded` | int64, nullable | No | Funding still needed this month to stay on track. Corresponds to "Underfunded" in web/mobile. |
| `goal_overall_funded` | int64, nullable | No | Total funded toward goal within current goal period |
| `goal_overall_left` | int64, nullable | No | Remaining funding needed to complete goal in current period |
| `goal_snoozed_at` | datetime, nullable | No | When the goal was snoozed; null if not snoozed |
| `deleted` | boolean | Yes | Deleted categories only included in delta requests |

**Goal Cadence Values (`goal_cadence`):**

| Value | Repeats |
|---|---|
| `0` | None (use with `goal_cadence_frequency`) |
| `1` | Monthly × `goal_cadence_frequency` (e.g., frequency=2 → every other month) |
| `2` | Weekly × `goal_cadence_frequency` |
| `3` | Every 2 Months (frequency ignored) |
| `4` | Every 3 Months (frequency ignored) |
| `5` | Every 4 Months (frequency ignored) |
| `6` | Every 5 Months (frequency ignored) |
| `7` | Every 6 Months (frequency ignored) |
| `8` | Every 7 Months (frequency ignored) |
| `9` | Every 8 Months (frequency ignored) |
| `10` | Every 9 Months (frequency ignored) |
| `11` | Every 10 Months (frequency ignored) |
| `12` | Every 11 Months (frequency ignored) |
| `13` | Yearly × `goal_cadence_frequency` |
| `14` | Every 2 Years (frequency ignored) |

**Goal Types:**

| Code | Name | Description |
|---|---|---|
| `TB` | Target Category Balance | Save up to a target amount |
| `TBD` | Target Category Balance by Date | Save a target amount by a specific date |
| `MF` | Monthly Funding | Fund a set amount each month |
| `NEED` | Plan Your Spending | Spend a set amount on a recurring cadence |
| `DEBT` | Debt Payoff | Pay off a linked debt account |

### `SaveCategory`

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string, nullable | No | |
| `note` | string, nullable | No | |
| `category_group_id` | uuid | No | |
| `goal_target` | int64, nullable | No | If set and no goal exists, creates a monthly NEED goal with this amount |
| `goal_target_date` | date, nullable | No | |

### `NewCategory` (for POST)
Extends `SaveCategory` with `name` and `category_group_id` both **required**.

### `ExistingCategory` (for PATCH)
All `SaveCategory` fields optional.

### `SaveMonthCategory`
```
budgeted  (int64, required)  — assigned amount in milliunits
```

### `SaveCategoryGroup`
```
name  (string, required, maxLength: 50)
```

### `CategoriesResponse`
```
data.category_groups[]  (CategoryGroupWithCategories[], required)
data.server_knowledge   (int64, required)
```

### `CategoryResponse`
```
data.category  (Category, required)
```

### `SaveCategoryResponse`
```
data.category         (Category, required)
data.server_knowledge (int64, required)
```

### `SaveCategoryGroupResponse`
```
data.category_group   (CategoryGroup, required)
data.server_knowledge (int64, required)
```

---

## 21. Schemas — Payees & Locations

### `Payee`

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | uuid | Yes | |
| `name` | string | Yes | |
| `transfer_account_id` | string, nullable | No | If a transfer payee, the `account_id` this payee transfers to |
| `deleted` | boolean | Yes | Deleted payees only included in delta requests |

### `SavePayee`
```
name  (string, not nullable, maxLength: 500)
```

### `PayeesResponse`
```
data.payees[]         (Payee[], required)
data.server_knowledge (int64, required)
```

### `PayeeResponse`
```
data.payee  (Payee, required)
```

### `SavePayeeResponse`
```
data.payee            (Payee, required)
data.server_knowledge (int64, required)
```

### `PayeeLocation`

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | uuid | Yes | |
| `payee_id` | uuid | Yes | Associated payee |
| `latitude` | string | Yes | GPS latitude |
| `longitude` | string | Yes | GPS longitude |
| `deleted` | boolean | Yes | Deleted locations only included in delta requests |

### `PayeeLocationsResponse`
```
data.payee_locations[]  (PayeeLocation[], required)
```
*(No `server_knowledge` — this endpoint does not support delta requests)*

### `PayeeLocationResponse`
```
data.payee_location  (PayeeLocation, required)
```

---

## 22. Schemas — Months

### `MonthSummary`

| Field | Type | Required | Description |
|---|---|---|---|
| `month` | date | Yes | Month in ISO format (first day of the month) |
| `note` | string, nullable | No | Month note |
| `income` | int64 | Yes | Total transactions categorized to "Inflow: Ready to Assign" |
| `budgeted` | int64 | Yes | Total assigned (budgeted) amount in milliunits |
| `activity` | int64 | Yes | Total transaction activity, **excluding** "Inflow: Ready to Assign" |
| `to_be_budgeted` | int64 | Yes | Available amount for "Ready to Assign" in milliunits |
| `age_of_money` | int32, nullable | No | Age of Money in days as of this month |
| `deleted` | boolean | Yes | Deleted months only included in delta requests |

### `MonthDetail`

Extends `MonthSummary`, adding:

```
categories[]  (Category[], required)  — amounts are specific to this month's {month} parameter
```

### `MonthSummariesResponse`
```
data.months[]         (MonthSummary[], required)
data.server_knowledge (int64, required)
```

### `MonthDetailResponse`
```
data.month  (MonthDetail, required)
```
*(No `server_knowledge` in this response)*

---

## 23. Schemas — Money Movements

### `MoneyMovement`

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | uuid | Yes | |
| `amount` | int64 | Yes | Amount moved in milliunits |
| `month` | date, nullable | No | Month of the movement (e.g. `2024-01-01`) |
| `moved_at` | datetime, nullable | No | Server timestamp when the movement was processed |
| `note` | string, nullable | No | |
| `money_movement_group_id` | uuid, nullable | No | The group this movement belongs to |
| `performed_by_user_id` | uuid, nullable | No | The user who performed the movement |
| `from_category_id` | uuid, nullable | No | Category money was moved **from** |
| `to_category_id` | uuid, nullable | No | Category money was moved **to** |

### `MoneyMovementGroup`

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | uuid | Yes | |
| `group_created_at` | datetime | Yes | When the group was created |
| `month` | date | Yes | Month of the group (e.g. `2024-01-01`) |
| `note` | string, nullable | No | |
| `performed_by_user_id` | uuid, nullable | No | The user who performed this group of movements |

### `MoneyMovementsResponse`
```
data.money_movements[]  (MoneyMovement[], required)
data.server_knowledge   (int64, required)
```

### `MoneyMovementGroupsResponse`
```
data.money_movement_groups[]  (MoneyMovementGroup[], required)
data.server_knowledge         (int64, required)
```

---

## 24. Schemas — Transactions

### `TransactionSummary`

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | Yes | |
| `date` | date | Yes | ISO format (e.g. `2016-12-01`) |
| `amount` | int64 | Yes | Amount in milliunits (negative = outflow) |
| `memo` | string, nullable | No | |
| `cleared` | TransactionClearedStatus | Yes | See enum |
| `approved` | boolean | Yes | Whether approved |
| `flag_color` | TransactionFlagColor, nullable | No | See enum |
| `flag_name` | TransactionFlagName, nullable | No | User-defined flag label (free text) |
| `account_id` | uuid | Yes | |
| `payee_id` | uuid, nullable | No | |
| `category_id` | uuid, nullable | No | |
| `transfer_account_id` | uuid, nullable | No | If a transfer, the destination account |
| `transfer_transaction_id` | string, nullable | No | If a transfer, the id of the other side |
| `matched_transaction_id` | string, nullable | No | If matched to an imported transaction |
| `import_id` | string, nullable | No | Unique per account. Format: `YNAB:[milliunit_amount]:[iso_date]:[occurrence]` |
| `import_payee_name` | string, nullable | No | Payee name used when importing (after any rename rules) |
| `import_payee_name_original` | string, nullable | No | Original payee name as it appeared on the statement (before rename rules) |
| `debt_transaction_type` | string, nullable | No | For debt/loan accounts — see DebtTransactionType enum |
| `deleted` | boolean | Yes | Deleted transactions only included in delta requests |

### `TransactionDetail`

Extends `TransactionSummary`, adding:

| Field | Type | Required | Description |
|---|---|---|---|
| `account_name` | string | Yes | |
| `payee_name` | string, nullable | No | |
| `category_name` | string, nullable | No | `"Split"` if split transaction |
| `subtransactions` | SubTransaction[] | Yes | Empty array if not a split |

### `HybridTransaction`

Extends `TransactionSummary`, adding:

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | string | Yes | `"transaction"` or `"subtransaction"` |
| `parent_transaction_id` | string, nullable | No | Parent transaction id (for subtransaction types; null for transaction types) |
| `account_name` | string | Yes | |
| `payee_name` | string, nullable | No | |
| `category_name` | string | Yes | `"Split"` if split transaction |

### `SubTransaction`

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | Yes | |
| `transaction_id` | string | Yes | Parent transaction id |
| `amount` | int64 | Yes | Amount in milliunits |
| `memo` | string, nullable | No | |
| `payee_id` | uuid, nullable | No | |
| `payee_name` | string, nullable | No | |
| `category_id` | uuid, nullable | No | |
| `category_name` | string, nullable | No | |
| `transfer_account_id` | uuid, nullable | No | If a transfer, the destination account |
| `transfer_transaction_id` | string, nullable | No | If a transfer, the id of the other side |
| `deleted` | boolean | Yes | Deleted subtransactions only included in delta requests |

### `SaveTransactionWithOptionalFields`

All fields optional. Base type for create/update operations.

| Field | Type | Notes |
|---|---|---|
| `account_id` | uuid | |
| `date` | date | Future dates not permitted. Split transaction dates cannot be changed. |
| `amount` | int64 | Split transaction amounts cannot be changed. |
| `payee_id` | uuid, nullable | For transfers: use target account's `transfer_payee_id` |
| `payee_name` | string (max 200), nullable | |
| `category_id` | uuid, nullable | `null` for splits. Cannot change if already a split. Credit Card Payment categories ignored. |
| `memo` | string (max 500), nullable | |
| `cleared` | TransactionClearedStatus | |
| `approved` | boolean | Defaults to `false` |
| `flag_color` | TransactionFlagColor | |
| `subtransactions` | SaveSubTransaction[] | Updating subtransactions on an existing split is not supported. |

### `NewTransaction`
Extends `SaveTransactionWithOptionalFields`, adding `import_id` (string, max 36, nullable).

### `ExistingTransaction`
All `SaveTransactionWithOptionalFields` fields (no additional fields).

### `SaveTransactionWithIdOrImportId`
Extends `SaveTransactionWithOptionalFields`, adding:
- `id` (string, nullable) — used for lookup if provided
- `import_id` (string, max 36, nullable) — used for lookup if `id` is null. Cannot update an existing `import_id`.

### `TransactionsResponse`
```
data.transactions[]   (TransactionDetail[], required)
data.server_knowledge (int64, required)
```

### `HybridTransactionsResponse`
```
data.transactions[]   (HybridTransaction[], required)
data.server_knowledge (int64, optional)
```

### `TransactionResponse`
```
data.transaction      (TransactionDetail, required)
data.server_knowledge (int64, required)
```

### `SaveTransactionsResponse`
```
data.transaction_ids[]       (string[], required)    — all saved transaction ids
data.transaction             (TransactionDetail)     — single created (single-create only)
data.transactions[]          (TransactionDetail[])   — multiple created (bulk-create only)
data.duplicate_import_ids[]  (string[])              — import_ids not created due to conflict
data.server_knowledge        (int64, required)
```

### `TransactionsImportResponse`
```
data.transaction_ids[]  (string[], required)  — list of imported transaction ids
```

---

## 25. Schemas — Scheduled Transactions

### `ScheduledTransactionSummary`

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | uuid | Yes | |
| `date_first` | date | Yes | The **first** date for which this scheduled transaction was scheduled |
| `date_next` | date | Yes | The **next** date for which this scheduled transaction is scheduled |
| `frequency` | ScheduledTransactionFrequency | Yes | See frequency enum |
| `amount` | int64 | Yes | Amount in milliunits |
| `memo` | string, nullable | No | |
| `flag_color` | TransactionFlagColor, nullable | No | |
| `flag_name` | TransactionFlagName, nullable | No | |
| `account_id` | uuid | Yes | |
| `payee_id` | uuid, nullable | No | |
| `category_id` | uuid, nullable | No | |
| `transfer_account_id` | uuid, nullable | No | If a transfer, the destination account |
| `deleted` | boolean | Yes | Deleted scheduled transactions only included in delta requests |

### `ScheduledTransactionDetail`

Extends `ScheduledTransactionSummary`, adding:

| Field | Type | Required | Description |
|---|---|---|---|
| `account_name` | string | Yes | |
| `payee_name` | string, nullable | No | |
| `category_name` | string, nullable | No | `"Split"` if split scheduled transaction |
| `subtransactions` | ScheduledSubTransaction[] | Yes | Empty if not a split |

### `ScheduledSubTransaction`

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | uuid | Yes | |
| `scheduled_transaction_id` | uuid | Yes | Parent scheduled transaction |
| `amount` | int64 | Yes | Amount in milliunits |
| `memo` | string, nullable | No | |
| `payee_id` | uuid, nullable | No | |
| `payee_name` | string, nullable | No | |
| `category_id` | uuid, nullable | No | |
| `category_name` | string, nullable | No | |
| `transfer_account_id` | uuid, nullable | No | If a transfer, the destination account |
| `deleted` | boolean | Yes | Deleted scheduled subtransactions only included in delta requests |

### `SaveScheduledTransaction`

| Field | Type | Required | Description |
|---|---|---|---|
| `account_id` | uuid | Yes | |
| `date` | date | Yes | Future date in ISO format. No more than 5 years in the future. |
| `amount` | int64 | No | Amount in milliunits |
| `payee_id` | uuid, nullable | No | For transfers: use target account's `transfer_payee_id` |
| `payee_name` | string (max 200), nullable | No | Resolves by (1) matching name or (2) creates new payee |
| `category_id` | uuid, nullable | No | Credit Card Payment categories not permitted. Split scheduled transactions not supported. |
| `memo` | string (max 500), nullable | No | |
| `flag_color` | TransactionFlagColor | No | |
| `frequency` | ScheduledTransactionFrequency | No | |

### `ScheduledTransactionsResponse`
```
data.scheduled_transactions[]  (ScheduledTransactionDetail[], required)
data.server_knowledge          (int64, required)
```

### `ScheduledTransactionResponse`
```
data.scheduled_transaction  (ScheduledTransactionDetail, required)
```

---

## 26. Enumerations

### `AccountType`

```
checking         — Checking account
savings          — Savings account
cash             — Cash account
creditCard       — Credit card
lineOfCredit     — Line of credit
otherAsset       — Other asset
otherLiability   — Other liability
mortgage         — Mortgage loan
autoLoan         — Auto loan
studentLoan      — Student loan
personalLoan     — Personal loan
medicalDebt      — Medical debt
otherDebt        — Other debt
```

### `TransactionClearedStatus`

```
cleared      — Transaction has cleared the bank
uncleared    — Transaction has not yet cleared
reconciled   — Transaction has been reconciled
```

### `TransactionFlagColor`

```
red
orange
yellow
green
blue
purple
""      (empty string — clears the flag)
null    (no flag)
```

### `TransactionFlagName`

Free-text string (or null). The user-defined name associated with a flag color. No fixed enum values.

### `DebtTransactionType`

For transactions on debt/loan accounts:

```
payment
refund
fee
interest
escrow
balanceAdjustment
credit
charge
null
```

### `ScheduledTransactionFrequency`

```
never
daily
weekly
everyOtherWeek
twiceAMonth
every4Weeks
monthly
everyOtherMonth
every3Months
every4Months
twiceAYear
yearly
everyOtherYear
```

### `Goal Type Codes`

| Code | Full Name |
|---|---|
| `TB` | Target Category Balance |
| `TBD` | Target Category Balance by Date |
| `MF` | Monthly Funding |
| `NEED` | Plan Your Spending |
| `DEBT` | Debt Payoff |

---

## 27. Project-Specific Notes

### Milliunits Convention

YNAB stores all monetary values as integer milliunits (value × 1000). **This project follows this exact convention.** All monetary amounts in the database are stored as milliunits and converted to display currency **only in Jinja2 templates** via the `milliunit_to_dollars` filter.

> Never store floating-point dollars. Never convert in service or router code.

### Soft Deletes

YNAB never hard-deletes entities. Deleted entities have `deleted: true` and are **only returned in delta requests** (when `last_knowledge_of_server` is provided). This project mirrors this: all YNAB entity deletes set `deleted = True`, never hard-delete.

### Delta Sync

The sync service stores and uses `server_knowledge` to implement efficient incremental syncs. Persist the returned `server_knowledge` value after each sync and pass it as `last_knowledge_of_server` on the next sync call.

### `plan_id` Shortcuts

| Value | Meaning |
|---|---|
| `"last-used"` | Most recently accessed plan |
| `"default"` | Plan selected during OAuth authorization |

### Transfers Between Accounts

To create a transfer between two accounts, set `payee_id` to the **destination account's `transfer_payee_id`** (found on the Account object). Do not use account IDs directly in the payee field.

### Credit Card Payment Categories

Credit Card Payment categories are **not permitted** in transaction create/update operations and will be silently ignored if supplied.

### Split Transactions

- Set `category_id = null` and provide `subtransactions[]` to create a split
- Once a transaction is a split, its `category_id` cannot be changed
- Subtransaction amounts sum must equal the parent transaction amount
- Updating subtransactions on an existing split is not supported via the API
- Split scheduled transactions are not currently supported

### Scheduled Transaction Date Constraint

The `date` field for scheduled transactions must be a future date no more than **5 years** in the future.

### `import_id` Format

Recommended format for file/direct import compatibility:
```
YNAB:[milliunit_amount]:[iso_date]:[occurrence]
```
Examples:
- `-$294.23 on 2015-12-30`: `YNAB:-294230:2015-12-30:1`
- Second occurrence same day/amount: `YNAB:-294230:2015-12-30:2`

Max length: 36 characters. Must be unique per account. Conflicts return HTTP 409.

### `HybridTransaction` vs `TransactionDetail`

- `TransactionDetail` is returned by most transaction endpoints — each transaction is a single row with a `subtransactions[]` array for splits
- `HybridTransaction` is returned by category, payee, and legacy filtered queries — each split's subtransactions appear as separate flat rows of type `"subtransaction"` alongside the parent of type `"transaction"`

---

## 28. Changelog

| Version | Date | Changes |
|---|---|---|
| 1.79.0 | 2026-03-05 | All endpoints migrated from `/budgets/{budget_id}` to `/plans/{plan_id}`. Response JSON keys: `budgets`→`plans`, `default_budget`→`default_plan`, `budget`→`plan`. Legacy `/budgets/` paths remain functional. |
| 1.78.0 | 2026-02-25 | POST endpoints for creating categories and category groups. PATCH for updating category groups. `goal_target` and `goal_target_date` support in category create/update. `goal_target_date` replaces deprecated `goal_target_month`. GET endpoints for money movements and money movement groups (with `server_knowledge` in response). `budget_id` parameter renamed to `plan_id`. |
| 1.77.0 | 2025-08-11 | `debt_original_balance` deprecated; always returns null. |
| 1.76.0 | 2025-08-05 | `goal_snoozed_at` datetime field exposed on Category. |
| 1.75.0 | 2025-06-30 | Removed incorrect `transaction_ids` object from single transaction GET response. Added `transaction_ids` to POST/PATCH transaction responses. |
| 1.74.0 | 2025-03-03 | PUT and DELETE endpoints for scheduled transactions. `payee_name` and `category_name` added to subtransactions. `goal_target` now updatable for categories. |
| 1.73.0 | 2025-01-29 | `X-Rate-Limit` header removed from 429 responses. |
| 1.72.0 | 2024-07-10 | `GET /plans/{plan_id}/months/{month}/transactions` endpoint added. |
| 1.71.0 | 2024-06-03 | Scheduled transaction creation (POST) support added. |
| 1.70.0 | 2024-06-12 | `goal_needs_whole_amount` field added to Category (indicates "Set Aside" vs "Refill" for NEED goals). |
| 1.69.0 | 2024-05-14 | Payee name update (PATCH) support added. |
| 1.68.1 | 2024-04-24 | `server_knowledge` removed from single category resource (`GET /categories/{id}`) responses. |
| 1.68.0 | 2024-02-26 | `flag_name` field added to Transaction and ScheduledTransaction response objects. |
| 1.0.0 | 2018-06-19 | Initial API release. |

---

## 29. Support & Resources

| Resource | Details |
|---|---|
| API Documentation | https://api.ynab.com |
| API Endpoint Reference | https://api.ynab.com/v1 |
| API Status | https://ynabstatus.com |
| Support Email | api@ynab.com (up to 1 week response time; limited support available) |
| OpenAPI Spec (YAML) | https://api.ynab.com/papi/open_api_spec.yaml |
| Official JavaScript SDK | npm: `ynab` |
| Official Ruby SDK | RubyGems: `ynab` |
| Official Python SDK | PyPI: `ynab` |
| Community SDKs | .NET, Elixir, Go, Java, Julia, Kotlin, Perl, PHP, PowerShell, R, Rust, Swift |
