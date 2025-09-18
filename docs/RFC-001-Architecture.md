# RFC-001: Архитектура MySLAVA v2

- Тип: RFC
- Статус: Draft (D1)
- Владельцы: TL/Core
- Дата: 2025-09-17
- Связанные документы: `docs/API-001-LicensingUsage.md`, `server/openapi/licensing.yml`, `docs/TESTPLAN-001-Init.md`, `docs/RISKS-001-Init.md`, `docs/BILLING-DECISION.md`

## Цели / Не-цели

- Цели:
  - Добавить backend лицензий/квот к имеющемуся Desktop (PyQt6 + Pyrogram).
  - Обеспечить учёт использования (usage) с идемпотентным резервированием/commit/rollback.
  - Ввести антиспам-политику и статусы аккаунта (активен/кулдаун/исключён).
  - Подготовить CI/CD, dev/stage окружения.
- Не-цели (в этом RFC):
  - End-to-end биллинг, окончательная безопасность (обфускация) и дизайн UI (этап 6).

## Контекст

Desktop-приложение (PyQt6 + Pyrogram) имеет рассылку (Broadcast) и модуль антиспама. Добавляем Backend (FastAPI + Postgres) для аутентификации, планов/подписок, лицензий и usage, а также вебхуков биллинга.

## Компоненты

- Desktop (PyQt6):
  - UI/настройки (`settings.ini`).
  - `BroadcastWorker`: отправка сообщений, контроль квоты.
  - `AntiSpamWorker`: детект PeerFlood/FloodWait и backoff/cooldown.
  - `LicenseClient`: JWT-аутентификация, `/license`, `/usage/*`.
  - Логи: HTML-журналы локально; опциональная телеметрия на backend.

- Backend (FastAPI + Postgres):
  - Auth (email/password; SSO в будущем), JWT RS256, device_fingerprint.
  - Licensing/Usage: проверка плана, резерв и commit/rollback использования.
  - Plans/Subscriptions: модели, биллинг, обновление limits.
  - Billing webhooks: Stripe/CloudPayments, идемпотентная обработка с редрайвом.
  - DevOps: dev/stage, observability (metrics/logs/traces), секреты.

- Внешние сервисы: Telegram (@SpamBot), Payment Provider (региональный выбор), ключевые риски тонкого доступа.

## Основные потоки

1) Логин
   - Desktop отправляет `POST /auth/login {email,password,device_fingerprint}`.
   - Ответ: `{token,user,exp}`. Токен хранится локально: `~/.myslava/license.json`.

2) Проверка лицензии
   - `GET /license` возвращает `{plan,status,quota,device_binding}`.
   - Значение `remaining` используется в UI.

3) Рассылка (usage reservation)
   - Перед отправкой: `POST /usage/reserve {messages, correlation_id}`.
   - После отправки: `POST /usage/commit {reservation_id,used}` или `POST /usage/rollback {reservation_id}`.
   - Идемпотентность по `correlation_id`, TTL=15 минут.

4) Антиспам
   - Обнаружение PeerFlood/FloodWait -> статус `Cooldown` с backoff.
   - Отображение по сигналам из UI или по таймеру.

## Состояния аккаунта

`Active -> Cooldown -> Active | Excluded`

- События: `PeerFlood`, `FloodWait`, `Timeout`, `ManualExclude`.
- Логика Desktop отвечает за списки и тайминг; backend предоставляет квоты и идемпотентные операции.

## Конфиг Desktop

- `settings.ini`: `api_base_url`, `jwt_public_key_fingerprint`, `flood.max_consecutive_errors`, `flood.cooldown_sec`, `anti_spam.enabled`.
- Хранение токена: `~/.myslava/license.json` (региональная директория OS), шифрование возможностями ОС.

## Логирование и телеметрия

- Локально: HTML-логи по сессиям.
- Backend (опционально): события анонимизированы, идемпотентны, с ретеншн-политикой.

## Безопасность

- JWT RS256, pinning публичного ключа в Desktop.
- TLS-only, HSTS. Device fingerprint в login и при обновлении токена.
- Валидация payload, RBAC на backend, rate limit 20 rps/token.

## Нефункциональные

- p95 < 300ms на `/license` в dev/stage.
- Идемпотентность reservations (TTL=15min), устойчивость к повторным запросам.
- Готовность к multi-provider billing (см. `docs/BILLING-DECISION.md`).

## Окружения и развертывание

- Environments: `dev`, `stage` (prod в этапе 6).
- Secrets: ключи JWT, DSN, provider keys в Secret Manager.
- Сборки Desktop: PyInstaller, подписи в этапе 6.

## Миграции и релизы

- DB схемы: модели `User`, `Plan`, `Subscription`, `Usage`, `Reservation`.
- Release train: мелкие релизы (weekly), совместимость API.

## Открытые вопросы

- Billing: Stripe или CloudPayments. См. `docs/BILLING-DECISION.md`.
- Device binding: кол-во устройств на аккаунт.
- Телеметрия: нужна ли анонимная.

---

Appendix A: упрощённая схема

Desktop приложение <= Backend API (FastAPI) <= Postgres
                         \
                         Payment Provider, @SpamBot
