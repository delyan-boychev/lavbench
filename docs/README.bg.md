# Ръководство за разработчици и документация на LavBench

Добре дошли в директорията с техническа документация на платформата LavBench. Тази папка съдържа ръководства за разработчици, изходни файлове за документацията в Sphinx, архитектурни спецификации и шаблони на скриптове за персонализиран оценител.

---

## Бърз достъп и карта на сайта

| Ресурс | URL / Път | Целева аудитория | Описание |
| :--- | :--- | :--- | :--- |
| **Swagger UI** | `http://localhost:5001/apidoc/swagger/` | Всички разработчици | Интерактивна документация за REST API и SSE крайни точки. |
| **Архитектурна спецификация** | [`source/architecture.md`](source/architecture.md) | Сътрудници и DevOps | Системна архитектура, разпределение на ресурсите за работни възли, SSE конвейери и слоеве за сигурност. |
| **Ръководство за персонализирани оценители** | [`custom-evaluators.md`](custom-evaluators.md) | Организатори на състезания | Пълен договор на модула, AST валидация и шаблони на скриптове за персонализирани метрики. |
| **Ръководство за администратора** | [`../guides/en/admin_guide.md`](../guides/en/admin_guide.md) | Администратори и организатори | Жизнен цикъл на състезанията, отстраняване на проблеми при изграждане на Docker образи, настройка на работните възли и правила за резервни копия. |
| **Ръководство за портала на журито** | [`../guides/en/jury_guide.md`](../guides/en/jury_guide.md) | Жури на състезанието | Наблюдение на решенията, диагностика при изграждане, двойно сляпо оценяване за поверителност и ръчно оценяване. |
| **Ръководство за състезателя** | [`../guides/en/competitor_guide.md`](../guides/en/competitor_guide.md) | Участници | Изпращане на бележници, предварителна AST валидация, конвейер на състоянията и отстраняване на проблеми. |

---

## 1. Насоки за разработчици на потребителския интерфейс

### Конвейер за типове на API

Потребителският интерфейс използва автоматизиран конвейер за типове, който извлича TypeScript дефиниции директно от Pydantic схемите на сървърната част:

```bash
cd frontend

# 1. Ensure backend is running (port 5001), then fetch OpenAPI spec & generate types:
npm run generate-api-types       # openapi-typescript → src/types/api.d.ts

# Over the compose stack the spec is also reachable through nginx (:80/apidoc/openapi.json):
API_SPEC_URL=http://localhost:80/apidoc/openapi.json npm run generate-api-types

# 2. Validate all JSDoc types and React component props:
npm run check-types              # tsc --noEmit (0 errors required)
```

Задачата за непрекъсната интеграция `docker-build` генерира наново `api.d.ts` **и** моментните снимки на спецификацията в `docs/source/api/` (+ `docs/source/api_spec.rst`) от работещата на живо система и **завършва с грешка при разминаване**, така че съхранените в хранилището типове и снимки винаги съответстват на OpenAPI спецификацията на сървърната част. Обновете ги локално чрез:

```
cd frontend && API_SPEC_URL=http://localhost:80/apidoc/openapi.json npm run generate-api-types
API_SPEC_URL=http://localhost:80/apidoc/openapi.json make -C docs fetch-spec
```

### Основни конвенции за потребителския интерфейс:
- **Автентификация**: `httpOnly` бисквитка (`auth_token`). `ApiService` автоматично управлява запазването на бисквитките.
- **SSE поточно предаване**: 7 крайни точки на живо използват Server-Sent Events. Свържете се чрез `new EventSource(url)` с автоматична оторизация чрез бисквитки.
- **Кодове за грешки**: Всички отговори за грешка от API връщат `{"error": "<message>", "code": "ERR_CODE"}`. Съпоставете `data.code` към потребителски низове за превод чрез `t('api.' + data.code)`.
- **Симетрия на i18n преводите**: Изпълнете `python frontend/scripts/check_translations.py`, за да гарантирате пълно съответствие между файловете с преводи за `en` и `bg`.

---

## 2. Насоки за разработчици на сървърната част

### Шаблон за реализация на крайни точки (spectree + Pydantic v2)

Всяка крайна точка в сървърната част трябва да използва Pydantic v2 схеми и декоратори `@api.validate` от spectree за валидация на заявките и отговорите:

```python
from spectree import Response
from utils.spec import api
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

### Основни конвенции за сървърната част:
- **Стандарт за кодове за грешки**: Използвайте `err("ERR_CODE", status_code)` от `utils/error_utils.py`. Всеки код `ERR_*` трябва да бъде регистриран в `DEFAULT_ERROR_MESSAGES` и преведен както за `en`, така и за `bg` езиковите версии.
- **Грешки в схемите**: Персонализираните валидатори на полета в Pydantic генерират `SchemaError("ERR_CODE", "Message")` от `schemas/exceptions.py`.
- **Проверка на кодовете за грешки**: Изпълнете `python backend/scripts/check_error_codes.py` преди да отворите заявка за сливане (PR).
- **Анотации за типове**: Целият изходен код на сървърната част трябва да преминава `mypy . --no-incremental` с 0 грешки.

---

## 3. Персонализирани оценители и шаблони

При създаване на скриптове за персонализиран оценител за задачи:
- Направете справка с [`custom-evaluators.md`](custom-evaluators.md) за договора от 4 задължителни променливи на модула (`METRIC_NAME`, `SUBMISSION_COLUMNS`, `LABELS_COLUMNS`, `EVALUATOR_OPTIONS`) и сигнатурата на `evaluate()`.
- Разгледайте примерните шаблони в `docs/evaluator_templates/`:
  - [`evaluator_custom_template.py`](evaluator_templates/evaluator_custom_template.py) — Изчерпателен референтен шаблон.
  - [`evaluator_ht1_audio.py`](evaluator_templates/evaluator_ht1_audio.py) — Класификация на аудио.
  - [`evaluator_ht2_delivery.py`](evaluator_templates/evaluator_ht2_delivery.py) — Навигация за доставки в решетка.
  - [`evaluator_ht3_animal.py`](evaluator_templates/evaluator_ht3_animal.py) — Логическа дедукция за животни.

---

## 4. Изграждане на документацията със Sphinx

Sphinx компилира проектната документация и автоматично генерираните справки за API (autodoc) в HTML:

```bash
cd docs

# 1. Install Sphinx requirements
pip install -r requirements.txt

# 2. Build HTML output
make html

# Output is generated in docs/build/ (open docs/build/index.html in a browser)

# 3. Bulgarian build (sources: docs/source/bg/ — guides symlinked from
#    guides/bg/, architecture.md translated via scripts/translate_gemini.py):
make html-bg
# Output is generated in docs/build/html-bg/
```

### Превключвател на езика (EN ↔ BG)

На всяка страница (в страничната лента и мобилната горна лента) се изобразява бутон за език, който води
към **същата страница** в другата версия. Предполага се, че българската версия е внедрена
под `bg/` спрямо корена на английската версия — напр.:

```bash
# Serve docs/build/ at /docs/ and docs/build/html-bg/ as /docs/bg/
python3 -m http.server 8080 --directory docs/build
# open http://localhost:8080/ -> EN docs, button links to /bg/competitor_guide
```

Превключвателят се намира в `docs/source/_templates/layout.html`
(макрос `lang_switch_link`, със стилове в `_static/css/custom.css`).

### Работен процес за превод

Българските преводи се генерират с [`../scripts/translate_gemini.py`](../scripts/translate_gemini.py) (Gemini API, с ключ в `.gemini-api-key` в корена на хранилището — изключен чрез `.gitignore`). Скриптът превежда `frontend/public/locales`, `guides/en/` → `guides/bg/`, `docs/README.md` → `docs/README.bg.md`, а с флага `--docs` превежда и файловете `docs/source/*.md` в `docs/source/bg/`. Ръководствата със символни връзки от `guides/` се отразяват огледално в `docs/source/bg/` (никога не се превеждат повторно); входната точка за изграждане на българската документация е `docs/source/bg/index.rst`. Изпълнете `python3 scripts/translate_gemini.py --dry-run` за пробно изпълнение и проверете резултата с `python3 frontend/scripts/check_translations.py` и `make html-bg`. Вижте CONTRIBUTING.md → „Translating UI strings and docs“.
