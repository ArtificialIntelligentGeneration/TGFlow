# ROADMAP: Этапы 2–6

## Этап 2: Backend лицензий/квот
- Реализовать модели `User`, `Plan`, `Subscription`, `Usage`, `Reservation`
- Эндпоинты: `/auth/login`, `/license`, `/usage/reserve|commit|rollback`, `/plans`
- Идемпотентность reservation, TTL, конкуренция
- Тесты API, p95 цели

## Этап 3: Интеграция Desktop
- `LicenseClient` + хранение токена
- Обновления UI: квота/остаток, ошибки 401/402/429
- Журналирование HTML, обработка офлайн режима `/license`

## Этап 4: Антиспам
- `AntiSpamWorker` backoff/cooldown, статусы аккаунта
- Интеграция со `@SpamBot` (моки)
- Настройки `flood.*` в `settings.ini`

## Этап 5: Биллинг
- `/billing/checkout` и вебхуки провайдера
- Синхронизация подписок -> планы/квоты
- Dunning/переходы статусов (active/past_due/canceled)

## Этап 6: Безопасность и релизы
- Обфускация Desktop, pinning, подписи сборок
- Секреты/конфигурации, мониторинг
- Релизный процесс, установщик
