# Ръководство за разработчици и документация на LavBench

Добре дошли в директорията с техническа документация на платформата LavBench. Тази папка съдържа ръководства за разработчици, изходни файлове за Sphinx документация, архитектурни спецификации и шаблони за скриптове за персонализирано оценяване.

---

## Бърз достъп и карта на сайта

| Ресурс | URL / Път | Целева аудитория | Описание |
| :--- | :--- | :--- | :--- |
| **Swagger UI** | `http://localhost:5001/apidoc/swagger/` | Всички разработчици | Интерактивна документация за REST API и SSE крайни точки. |
| **Architecture Specification** | [`source/architecture.md`](source/architecture.md) | Сътрудници и DevOps | Системна архитектура, бюджетиране на изпълнителите (workers), SSE конвейери и слоеве за сигурност. |
| **Custom Evaluator Guide** | [`custom-evaluators.md`](custom-evaluators.md) | Организатори на състезания | Пълен договор на модула, AST валидация и шаблони за скриптове за персонализирани метрики. |
| **Administrator Guide** | [`../guides/en/admin_guide.md`](../guides/en/admin_guide.md) | Администратори и организатори | Жизнен цикъл на състезанията, отстраняване на проблеми с компилирането на Docker, настройка на изпълнителите (workers) и правила за архивиране. |
| **Jury Portal Guide** | [`../guides/en/jury_guide.md`](../guides/en/jury_guide.md) | Жури на състезанието | Мониторинг на решенията, диагностика на сглобяването, поверителност с двоен сляп метод и ръчно оценяване. |
| **Competitor Guide** | [`../guides/en/competitor_guide.md`](../guides/en/competitor_guide.md) | Участници | Изпращане на бележници, предварителна AST валидация, конвейер на състоянието и отстраняване на проблеми. |

---

## 1. Насоки за разработчици на потребителския интерфейс (Frontend)

### Конвейер за типове на API

Потребителският интерфейс използва автоматизиран конвейер за типове за извличане на TypeScript дефиниции директно от Pydantic схемите на бекенда:

```bash
cd frontend

# 1. Ensure backend is running (port 5001), then fetch OpenAPI spec & generate types:
npm run generate-api-types       # openapi-typescript → src/types/api.d.ts

# Over the compose stack the spec is also reachable through nginx (:80/apidoc/openapi.json):
API_SPEC_URL=http://localhost:80/apidoc/openapi.json npm run generate-api-types

# 2. Validate all JSDoc types and React component props:
npm run check-types              # tsc --noEmit (0 errors required)
```

CI задачата `docker-build` регенерира `api.d.ts` **и** снимките на спецификацията в `docs/source/api/` (+ `docs/source/api_spec.rst`) от работещото приложение и **завършва с грешка при разминаване**, така че съхранените типове и снимки винаги съответстват на OpenAPI спецификацията на бекенда. Обновете ги локално с:

```
cd frontend && API_SPEC_URL=http://localhost:80/apidoc/openapi.json npm run generate-api-types
API_SPEC_URL=http://localhost:80/apidoc/openapi.json make -C docs fetch-spec
```

### Основни конвенции за потребителския интерфейс:
- **Автентикация**: `httpOnly` бисквитка (`auth_token`). `ApiService` автоматично управлява съхранението на бисквитките.
- **SSE поточно предаване**: 7 крайни точки на живо използват Server-Sent Events. Свързването става чрез `new EventSource(url)` с автоматична авторизация чрез бисквитки.
- **Кодове за грешки**: Всички отговори за грешка от API връщат `{"error": "<message>", "code": "ERR_CODE"}`. Съпоставете `data.code` към потребителски низове за превод чрез `t('api.' + data.code)`.
- **Паритет на i18n преводите**: Изпълнете `python frontend/scripts/check_translations.py`, за да осигурите симетрия между файловете с преводи на `en` и `bg`.

---

## 2. Насоки за разработчици на бекенда

### Шаблон за внедряване на крайни точки (spectree + Pydantic v2)

Всяка крайна точка на бекенда трябва да използва Pydantic v2 схеми и декоратори `@api.validate` от spectree за валидация на заявките/отговорите:

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
- **Стандарт за кодове за грешки**: Използвайте `err("ERR_CODE", status_code)` от `utils/error_utils.py`. Всеки `ERR_*` код трябва да бъде регистриран в `DEFAULT_ERROR_MESSAGES` и преведен както за `en`, така и за `bg` локализациите.
- **Грешки в схемите**: Персонализираните валидатори на полета в Pydantic извличат `SchemaError("ERR_CODE", "Message")` от `schemas/exceptions.py`.
- **Линтер за грешки**: Изпълнете `python backend/scripts/check_error_codes.py` преди изпращане на PR.
- **Аннотации за типове**: Целият изходен код на бекенда трябва да преминава `mypy . --no-incremental` с 0 грешки.

---

## 3. Персонализирани модули за оценяване и шаблони

При създаване на персонализирани скриптове за оценяване за задачи:
- Направете справка с [`custom-evaluators.md`](custom-evaluators.md) за договора от 4 задължителни променливи на модула (`METRIC_NAME`, `SUBMISSION_COLUMNS`, `LABELS_COLUMNS`, `EVALUATOR_OPTIONS`) и сигнатурата на `evaluate()`.
- Прегледайте примерните шаблони в `docs/evaluator_templates/`:
  - [`evaluator_custom_template.py`](evaluator_templates/evaluator_custom_template.py) — Подробен референтен шаблон.
  - [`evaluator_ht1_audio.py`](evaluator_templates/evaluator_ht1_audio.py) — Класификация на аудио.
  - [`evaluator_ht2_delivery.py`](evaluator_templates/evaluator_ht2_delivery.py) — Навигация за доставки в мрежа (grid).
  - [`evaluator_ht3_animal.py`](evaluator_templates/evaluator_ht3_animal.py) — Логика за дедукция при животни.

---

## 4. Изграждане на документация със Sphinx

Sphinx компилира документацията на проекта и autodoc справките за API в HTML:

```bash
cd docs

# 1. Install Sphinx requirements
pip install -r requirements.txt

# 2. Build HTML output
make html

# Output is generated in docs/build/html/ (open index.html in browser)

# 3. Bulgarian build (sources: docs/source/bg/ — guides symlinked from
#    guides/bg/, architecture.md translated via scripts/translate_gemini.py):
make html-bg
# Output is generated in docs/build/html-bg/
```

### Превключвател на езика (EN ↔ BG)

Бутон за език се изобразява на всяка страница (странична лента + мобилна горна лента) и води
към **същата страница** в другата версия. Предполага се, че bg версията е внедрена
под `bg/` спрямо корена на en версията — напр.:

```bash
# Serve docs/build/ at /docs/ and docs/build/html-bg/ as /docs/bg/
python3 -m http.server 8080 --directory docs/build
# open http://localhost:8080/ -> EN docs, button links to /bg/competitor_guide
```

Превключвателят се намира в `docs/source/_templates/layout.html`
(макрос `lang_switch_link`, със стилове в `_static/css/custom.css`).

### Работен процес за превод

Българските преводи се генерират с [`../scripts/translate_gemini.py`](../scripts/translate_gemini.py) (Gemini API, ключ в `.gemini-api-key` в корена на хранилището — в .gitignore). Скриптът превежда `frontend/public/locales`, `guides/en/` → `guides/bg/`, `docs/README.md` → `docs/README.bg.md`, а с опцията `--docs` превежда файловете `docs/source/*.md` в `docs/source/bg/`. Ръководствата, свързани чрез символични връзки от `guides/`, се огледално отразяват в `docs/source/bg/` (без да се превеждат повторно); входната точка за изграждане на bg документацията е `docs/source/bg/index.rst`. Изпълнете `python3 scripts/translate_gemini.py --dry-run` за предварителен преглед и потвърдете с `python3 frontend/scripts/check_translations.py` и `make html-bg`. Вижте CONTRIBUTING.md → "Translating UI strings and docs".
