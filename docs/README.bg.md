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
| **Ръководство за портала на журито** | [`../guides/en/jury_guide.md`](../guides/en/jury_guide.md) | Жури на състезанието | Наблюдение на решенията, диагностика при изграждане на образи, двойно сляпа поверителност и ръчно оценяване. |
| **Ръководство за състезателя** | [`../guides/en/competitor_guide.md`](../guides/en/competitor_guide.md) | Участници | Изпращане на бележници, предварителна AST валидация, конвейер на състоянията и отстраняване на проблеми. |
| **Бележка за интеграцията с nanoColab** | [`source/ops/nanocolab-integration.md`](source/ops/nanocolab-integration.md) | Екипът на nanoColab и DevOps | Как LavBench управлява `/v1` API на nanoColab: цикъл за синхронизация, едно събитие за етап или състезание, публикуване, пакет с папка за всяка задача, работни пространства и изпращане на решения от тях, съответствие на грешките, резервен вариант и заявки към nanoColab. |

---

## 1. Насоки за разработчици

Правилата и процедурите за писане на код са събрани на едно място — в [`AGENTS.md`](../AGENTS.md):
- структура на сървърната част и канонично импортиране, шаблони за маршрути, валидация с Pydantic и spectree, както и кодове за грешки (`err()`, `SchemaError`);
- конвенции за потребителския интерфейс и преводи (ключове `api.ERR_*`, множествени числа, скрипт за превод на български);
- конвейер за типове на API: генерирайте наново `frontend/src/types/api.d.ts` и `docs/source/api/spec.json` от работеща сървърна част с `npm run generate-api-types` и `make -C docs fetch-spec` (през стека на Docker Compose задайте променливата на средата `API_SPEC_URL=http://localhost:80/apidoc/openapi.json`); задачата за непрекъсната интеграция `docker-build` завършва с грешка при разминаване в който и да е от двата файла;
- проверките, които трябва да изпълните преди качване на промените в хранилището.

---

## 2. Персонализирани оценители и шаблони

При създаване на скриптове за персонализиран оценител за задачи:
- Направете справка с [`custom-evaluators.md`](custom-evaluators.md) за договора от 4 задължителни променливи на модула (`METRIC_NAME`, `SUBMISSION_COLUMNS`, `LABELS_COLUMNS`, `EVALUATOR_OPTIONS`) и сигнатурата на `evaluate()`.
- Разгледайте примерните шаблони в `docs/evaluator_templates/`:
  - [`evaluator_custom_template.py`](evaluator_templates/evaluator_custom_template.py) — Изчерпателен референтен шаблон.
  - [`evaluator_ht1_audio.py`](evaluator_templates/evaluator_ht1_audio.py) — Класификация на аудио.
  - [`evaluator_ht2_delivery.py`](evaluator_templates/evaluator_ht2_delivery.py) — Навигация за доставки в решетка.
  - [`evaluator_ht3_animal.py`](evaluator_templates/evaluator_ht3_animal.py) — Логическа дедукция за животни.

---

## 3. Изграждане на документацията със Sphinx

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
