# Лабораторная работа #5

![GitHub Classroom Workflow](../../workflows/GitHub%20Classroom%20Workflow/badge.svg?branch=master)

## OAuth2 Authorization

### Формулировка

На базе [Лабораторной работы #4](https://github.com/bmstu-rsoi/lab2-template) реализовать OAuth2 token-based
авторизацию.

* Для авторизации использовать OpenID Connect, в роли Identity Provider использовать стороннее решение.
* На Identity Provider настроить
  использование [Resource Owner Password flow](https://auth0.com/docs/authorization/flows/resource-owner-password-flow)
  (в одном запросе передается `clientId`, `clientSecret`, `username`, `password`).
* Все методы `/api/**` (кроме `/api/v1/authorize` и `/api/v1/callback`) на всех сервисах закрыть token-based
  авторизацией.
* В качестве токена использовать [JWT](https://jwt.io/introduction), для валидации токена
  использовать [JWKs](https://auth0.com/docs/security/tokens/json-web-tokens/json-web-key-sets), _запрос к Identity
  Provider делать не нужно_.
* JWT токен пробрасывать между сервисами, при получении запроса валидацию токена так же реализовать через JWKs.
* Убрать заголовок `X-User-Name` и получать пользователя из JWT-токена.
* Если авторизация некорректная (отсутствие токена, ошибка валидации JWT токена, закончилось время жизни токена
  (поле `exp` в payload)), то отдавать 401 ошибку.
* В `scope` достаточно указывать `openid profile email`.

### Требования

1. Для автоматических прогонов тестов в файле [autograding.json](.github/classroom/autograding.json)
   и [classroom.yml](.github/workflows/classroom.yml) заменить `<variant>` на ваш вариант.
1. Код хранить на Github, для сборки использовать Github Actions.
1. Каждый сервис должен быть завернут в docker.
1. В classroom.yml дописать шаги на сборку, прогон unit-тестов.

### Пояснения

1. В роли Identity Provider можно использовать любое решение, вот несколько рабочих вариантов:
    1. [Okta](https://developer.okta.com/docs/guides/)
    2. [Auth0](https://auth0.com/developers)
2. Для получения metadata для OpenID Connect можно
   использовать [Well-Known URI](https://auth0.com/docs/security/tokens/json-web-tokens/locate-json-web-key-sets):
   `https://[base-server-url]/.well-known/openid-configuration`.
3. Из Well-Known metadata можно получить Issuer URI и JWKs URI.
4. Для реализации OAuth2 можно использовать сторонние библиотеки.

### Настройка OAuth2/OIDC

Сервисы теперь принимают только запросы с заголовком `Authorization: Bearer <jwt>`. Валидируется подпись и срок
действия токена по JWKs (без запросов к Identity Provider). Пользовательское имя берется из claim
`preferred_username` / `email` / `name` / `sub` и используется в rental-service.

Переменные окружения (для всех сервисов):
* `OIDC_ISSUER` — issuer, который проверяется в токене.
* `OIDC_AUDIENCE` — aud, который проверяется в токене (по умолчанию = `OIDC_CLIENT_ID`).
* `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` — учётные данные клиента в IdP.
* `OIDC_TOKEN_URL` — endpoint токенов (используется в `/api/v1/authorize` и `/api/v1/callback`).
* `OIDC_WELL_KNOWN_URL` — опционально, если хотите подтянуть metadata и jwks при старте.
* `OIDC_JWKS` или `OIDC_JWKS_URL` — статичный набор ключей либо ссылка на JWKS (используется только для валидации).
* `OIDC_SCOPE` — запрашиваемые scope, по умолчанию `openid profile email`.
* `OIDC_REDIRECT_URI` — redirect_uri для обмена кода в `/api/v1/callback` (если используете auth code flow).

Как работает поток:
1. Получить токен через `/api/v1/authorize` (Resource Owner Password) или напрямую у IdP.
2. Все запросы к `/api/**` отправлять с `Authorization: Bearer <jwt>`.
3. Gateway пробрасывает токен дальше в cars/rental/payment, а сами сервисы валидируют JWT по JWKs.

### Быстрый запуск локально

1. Заполните переменные окружения из блока выше (можно через `.env`).
2. Соберите и поднимите всё: `docker compose up --build`.
3. Получите токен: `curl -X POST http://localhost:8080/api/v1/authorize -d "username=<u>&password=<p>&client_id=$OIDC_CLIENT_ID&client_secret=$OIDC_CLIENT_SECRET"`.
4. Используйте токен во всех запросах, например:  
   `curl -H "Authorization: Bearer <token>" "http://localhost:8080/api/v1/cars?page=1&size=10"`.

### Прием задания

1. При получении задания у вас создается fork этого репозитория для вашего пользователя.
2. После того как все тесты успешно завершатся, в Github Classroom на Dashboard будет отмечено успешное выполнение
   тестов.

### Варианты заданий

Распределение вариантов заданий аналогично [ЛР #2](https://github.com/bmstu-rsoi/lab2-template).