# Ръководство за разработчици и документация на LavBench

Добре дошли в директорията с техническа документация на платформата LavBench. Тази папка съдържа ръководства за разработчици, източници на документация за Sphinx, архитектурни спецификации и шаблони за скриптове за персонализирано оценяване.

---

## Бърз достъп и карта на сайта

| Ресурс | URL / Път | Целева аудитория | Описание |
| :--- | :--- | :--- | :--- |
| **Swagger UI** | `http://localhost:5001/apidoc/swagger/` | Всички разработчици | Интерактивна документация за REST API и SSE крайни точки. |
| **Спецификация на архитектурата** | [`source/architecture.md`](source/architecture.md) | Сътрудници и DevOps | Системна архитектура, бюджетиране на работници (workers), SSE конвейери и слоеве за сигурност. |
| **Ръководство за персонализирано оценяване** | [`custom-evaluators.md`](custom-evaluators.md) | Организатори на състезания | Пълен договорен интерфейс на модула, AST валидация и шаблони за скриптове за персонализирани метрики. |
| **Ръководство за администратора** | [`../guides/en/admin_guide.md`](../guides/en/admin_guide.md) | Администратори и организатори | Жизнен цикъл на състезанието, отстраняване на проблеми при изграждане на Docker, настройка на работници и правила за архивиране. |
| **Ръководство за портала на журито** | [`../guides/en/jury_guide.md`](../guides/en/jury_guide.md) | Жури на състезанието | Мониторинг на решенията, диагностика на изграждането, двойно сляпа поверителност и ръчно оценяване. |
| **Ръководство за състезателя** | [`../guides/en/competitor_guide.md`](../guides/en/competitor_guide.md) | Участници | Изпращане на бележник, предварителна AST валидация, конвейер на статусите и отстраняване на проблеми. |

---

## 1. Насоки за фронтенд разработчици

### Конвейер за API типове

Фронтендът използва автоматизиран конвейер за типове, за да извежда TypeScript дефиниции директно от Pydantic схемите на бекенда:

```bash
cd frontend

# 1. Уверете се, че бекендът работи (порт 5001), след което изтеглете OpenAPI спецификацията и генерирайте типове:
npm run generate-api-types       # openapi-typescript → src/types/api.d.ts

# През compose стека спецификацията е достъпна и през nginx (:80/apidoc/openapi.json):
API_SPEC_URL=http://localhost:80/apidoc/openapi.json npm run generate-api-types

# 2. Валидирайте всички JSDoc типове и пропове на React компоненти:
npm run check-types              # tsc --noEmit (изискват се 0 грешки)
```

CI задачата `docker-build` регенерира `api.d.ts` **и** снимките (snapshots) на спецификацията в `docs/source/api/` (+ `docs/source/api_spec.rst`) от работещия стек и **пропада при разминаване (drift)**, така че committed типовете и снимките винаги съответстват на OpenAPI спецификацията на бекенда. Опреснете ги локално с:

```
cd frontend && API_SPEC_URL=http://localhost:80/apidoc/openapi.json npm run generate-api-types
API_SPEC_URL=http://localhost:80/apidoc/openapi.json make -C docs fetch-spec
```

### Основни конвенции за фронтенда:
- **Автентификация**: `httpOnly` бисквитка (`auth_token`). `ApiService` автоматично управлява запазването на бисквитките.
- **SSE поточно предаване (Streaming)**: 7 активни крайни точки използват Server-Sent Events. Свързвайте се чрез `new EventSource(url)` с автоматична авторизация чрез бисквитки.
- **Кодове за грешки**: Всички API отговори за грешки връщат `{"error": "<message>", "code": "ERR_CODE"}`. Напасвайте `data.code` към преводни низове за потребителя чрез `t('api.' + data.code)`.
- **i18n паритет на преводите**: Изпълнете `python frontend/scripts/check_translations.py`, за да осигурите симетрия между преводните файлове за `en` и `bg`.

---

## 2. Насоки за бекенд разработчици

### Шаблон за внедряване на крайни точки (spectree + Pydantic v2)

Всяка крайна точка на бекенда трябва да използва Pydantic v2 схеми и декоратори `@api.validate` на spectree за валидация на заявката/отговора:

```python
from spectree import Response
from spec import api
from schemas.challenge import CreateChallengeSchema
from schemas.responses.challenge import ChallengeResponse

@challenges_bp.route("", methods=["POST"])
@login_required
@role_required(["admin"])
@api.validate(
    json=CreateChallengeSchema,
    resp=Response(HTTP_201=ChallengeResponse),
    tags=["Challenges"],
    security=[{"cookieAuth": []}],
)
def create_challenge(json: CreateChallengeSchema):
    """Creates a new competition challenge."""
    # json is the pre-validated CreateChallengeSchema instance
    challenge = Challenge(title=json.title, description=json.description)
    db.session.add(challenge)
    db.session.commit()
    return challenge.to_dict(), 201
```

### Основни конвенции за бекенда:
- **Стандарт за кодове за грешки**: Използвайте `err("ERR_CODE", status_code)` от `error_utils.py`. Всеки `ERR_*` код трябва да бъде регистриран в `DEFAULT_ERROR_MESSAGES` и преведен както в `en`, така и в `bg` локализациите.
- **Грешки в схемата**: Персонализираните валидатори на Pydantic полета хвърлят `SchemaError("ERR_CODE", "Message")` от `schemas/exceptions.py`.
- **Линтър за грешки**: Изпълнете `python backend/scripts/check_error_codes.py` преди изпращане на PR.
- **Аннотации на типовете**: Всички изходни кодове на бекенда трябва да преминават `mypy . --no-incremental` с 0 грешки.

---

## 3. Персонализирани оценители и шаблони

При създаване на персонализирани скриптове за оценяване за задачи:
- Направете справка с [`custom-evaluators.md`](custom-evaluators.md) за изисквания договорен интерфейс от 4 променливи на модула (`METRIC_NAME`, `SUBMISSION_COLUMNS`, `LABELS_COLUMNS`, `EVALUATOR_OPTIONS`) и сигнатурата на `evaluate()`.
- Прегледайте примерните шаблони в `docs/evaluator_templates/`:
  - [`evaluator_custom_template.py`](evaluator_templates/evaluator_custom_template.py) — Изчерпателен референтен шаблон.
  - [`evaluator_ht1_audio.py`](evaluator_templates/evaluator_ht1_audio.py) — Аудио класификация.
  - [`evaluator_ht2_delivery.py`](evaluator_templates/evaluator_ht2_delivery.py) — Навигация за доставяне по мрежа.
  - [`evaluator_ht3_animal.py`](evaluator_templates/evaluator_ht3_animal.py) — Логика за дедукция при животни.

---

## 4. Изграждане на Sphinx документация

Sphinx компилира документацията на проекта и autodoc API справките в HTML:

```bash
cd docs

# 1. Инсталирайте изискванията за Sphinx
pip install -r requirements.txt

# 2. Изградете HTML изхода
make html

# Изходът се генерира в docs/build/html/ (отворете index.html в браузъра)

# 3. Българска компилация (източници: docs/source/bg/ — ръководствата са символно свързани от
#    guides/bg/, architecture.md е преведен чрез scripts/translate_gemini.py):
make html-bg
# Изходът се генерира в docs/build/html-bg/
```

### Работен процес по превеждане

Българските преводи се генерират с [`../scripts/translate_gemini.py`](../scripts/translate_gemini.py) (Gemini API, ключ в `.gemini-api-key` в корена на хранилището — в `.gitignore`). Той превежда `frontend/public/locales`, `guides/en/` → `guides/bg/`, `docs/README.md` → `docs/README.bg.md`, а с опцията `--docs` превежда файловете `docs/source/*.md` в `docs/source/bg/`. Ръководствата, свързани със символни връзки от `guides/`, се огледално отразяват в `docs/source/bg/` (никога не се превеждат повторно); входната точка за компилиране на документацията на български е `docs/source/bg/index.rst`. Изпълнете `python3 scripts/translate_gemini.py --dry-run` за преглед и потвърдете с `python3 frontend/scripts/check_translations.py` и `make html-bg`. Вижте CONTRIBUTING.md → "Translating UI strings and docs".
