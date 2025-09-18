# API-001: Лицензии и учёт Usage

- Аутентификация: Bearer JWT (RS256)
- Ссылка на OpenAPI: `server/openapi/licensing.yml`

## Эндпоинты (черновик)

- POST /auth/login
  - Вход: `{ email, password, device_fingerprint }`
  - Выход: `{ token, user }`

- GET /license
  - Выход: `{ plan, status, quota{ monthly_limit, used, remaining, reset_at }, device_binding }`

- POST /usage/reserve
  - Вход: `{ messages, correlation_id }`
  - Выход: `{ reservation_id, reserved, remaining }`

- POST /usage/commit
  - Вход: `{ reservation_id, used }`
  - Выход: `{ ok }`

- POST /usage/rollback
  - Вход: `{ reservation_id }`
  - Выход: `{ ok }`

- GET /plans
  - Выход: `[{ id, name, price, currency, monthly_limit }]`

- POST /billing/checkout
  - Вход: `{ plan_id, return_url }`
  - Выход: `{ checkout_url }`

- POST /billing/webhook
  - Вход: `(provider payload)`
  - Выход: `{ ok }`

## Ошибки

- 401 Unauthorized
- 402 Payment Required
- 409 Conflict (reservation)
- 429 Too Many Requests
- 5xx Server Errors

## Идемпотентность

- Идентификатор `correlation_id` для резервирования, TTL=15 минут.

## Модели данных (high-level)

```json
{
  "User": {"id":"uuid","email":"string","created_at":"datetime"},
  "Subscription": {"id":"uuid","user_id":"uuid","plan_id":"uuid","status":"active|past_due|canceled","current_period_end":"datetime"},
  "Plan": {"id":"uuid","name":"Pro","monthly_limit":10000,"price":"decimal","currency":"USD"},
  "Usage": {"id":"uuid","user_id":"uuid","month_key":"YYYY-MM","used":1234,"updated_at":"datetime"},
  "Reservation": {"id":"uuid","user_id":"uuid","messages":100,"expires_at":"datetime","committed":false}
}
```
