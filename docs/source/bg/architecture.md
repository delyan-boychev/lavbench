# Системна архитектура и инфраструктура на LavBench

## 1. Общ преглед на системата

```text
Browser (React SPA) ──> Nginx (Port 80 / 443, HTTP(S) / SSE Reverse Proxy)
                            ├── Flask API Server (Port 5001, Gunicorn + gevent)
                            │     ├── PostgreSQL 15 (Primary Database)
                            │     ├── Redis (Celery Broker + Coordination: SSE pub/sub fan-out, worker_spec registry, submission fallback key, dirty-challenges set, dead-letter queue, GPU/build locks)
                            │     ├── Redis Cache (Private, server-only: leaderboard caches, locks, rate-limit counters, JWT blacklist — CACHE_REDIS_URL never given to external workers)
                            │     ├── Celery Beat (Periodic Scheduler: Backups, Watchdog)
                            │     └── Internal Celery Worker (System tasks only, inside Docker Compose, -Q celery,internal)
                            └── Remote Execution Workers (Celery evaluation-only workers: Docker container or host, consume cpu_queue)
                                  └── Sibling Sandbox Containers (--network none, --read-only, --cap-drop ALL)
```

---

## 2. Технологичен стек на компонентите

| Компонент | Технология | Роля и основни отговорности |
| :--- | :--- | :--- |
| **Frontend** | React 19 + Vite + Vanilla/Tailwind CSS | SPA с актуализации на живо чрез SSE, i18n (en/bg), JSDoc `@type` валидация (`tsc --noEmit`). |
| **API Server** | Flask 3.1 + Gunicorn + gevent + spectree | REST API крайни точки, Pydantic v2 валидация на заявки/отговори, SSE поточно предаване на събития. |
| **Primary Database** | PostgreSQL 15 | Потребители, състезания, етапи, задачи, решения, журнали за одит (`AuditLog`). |
| **Cache & Broker** | Redis | Celery брокер на задачи + **клиент за координация** за цялото споделено състояние между машините: SSE pub/sub разпращане, регистър на спецификациите на уъркърите (`worker_spec:<hostname>`), ключ за резервно решение, съвкупност от променени състезания (dirty-challenges), опашка за необработени съобщения (dead-letter queue), GPU/build заключвания. |
| **Dedicated Cache** | Redis (DB 1, `noeviction`, no persistence) | Самостоятелен, частен сървърен кеш: кешове за класацията, разпределени заключвания, броячи за ограничение на честотата (rate-limit) и черен списък за JWT токени (`CACHE_REDIS_URL`). Вътрешен контейнер — без порт към хоста; външните уъркъри никога не получават този URL адрес. |
| **Task Queue** | Celery 5.4 | Асинхронно изпълнение на задачи (оценяване на решения, компилиране на изображения, резервни копия на базата данни). |
| **Scheduler** | Celery Beat | Периодични задачи (контрольор за заседнали решения, график за автоматични резервни копия). |
| **Worker Nodes** | Celery Evaluation Worker | Уъркъри **само за оценяване**, консумиращи `cpu_queue`; изпълняват кода на състезателя в съседни Docker контейнери в пясъчна среда (`deploy-worker.sh` / `worker.env`). |

---

## 3. Поток на автентификация и авторизация

```text
1. User → POST /api/auth/login (username + SHA256(password))
2. API Server → verifies credentials → generates JWT with unique jti → sets httpOnly 'auth_token' cookie
3. Browser → subsequent API requests automatically transmit httpOnly cookie
4. Server → verify_token() middleware → checks Redis jti revocation blacklist → DB role lookup → authorizes
5. Logout → POST /api/auth/logout → clears cookie + blacklists jti in Redis (TTL = remaining token lifetime)
```

---

## 4. Пайплайн за предаване на решения и сигурност с изолация в пясъчна среда

```text
1. User uploads .ipynb → POST /api/challenges/<id>/parse-notebook
2. User selects code cells → POST /api/challenges/<id>/submit
3. Server: Pre-execution AST validation (IPython magic stripping, banned_imports check) → rate limit check → creates Submission → dispatches Celery evaluation job
4. Worker Node: picks up job → ensures task Docker image (lavbench_task_<id>) is compiled → seeds the run directory (submission script + task data snapshot) into the sandbox via put_archive
5. Hardened Sandbox Container: launches execution with zero-trust security parameters
6. Competitor Code: executes inside container → writes submission.parquet output (pulled back via get_archive)
7. Worker Evaluation Engine: evaluates submission.parquet against labels.parquet server-side (or runs evaluator.py) → updates Submission status & scores → publishes SSE event → invalidates leaderboard cache
```

### Параметри за изолация на контейнера в пясъчна среда

Кодът на състезателя се изпълнява в Docker контейнер с нулево доверие (zero-trust) и строги ограничения на ядрото на Linux (kernel caps):

| Параметър | Цел и гаранция за сигурност |
| :--- | :--- |
| `--network none` | Напълно деактивира мрежата на контейнера — предотвратява изтичане на данни и външни сокет повиквания. |
| `--cap-drop ALL` | Премахва всички възможности (capabilities) на ядрото на Linux — блокира сурови (raw) сокети, `mount()`, `ptrace()` и ескалация на привилегии. |
| `--read-only` | Монтира коренната файлова система само за четене — кодът на състезателя не може да променя системни бинарни файлове или библиотеки. |
| `--no-new-privileges` | Предотвратява ескалация на привилегиите на процеса чрез SUID бинарни файлове. |
| `--tmpfs /tmp:noexec,nosuid,size=128m` | Временна директория в оперативната памет с ограничен размер, която не може да изпълнява бинарни файлове или да използва дисково пространство на хоста. |
| `--memory-swap` = RAM Limit | Деактивира суап (swap) паметта — гарантира незабавно прекратяване от OOM на ядрото, ако се превиши лимитът на RAM паметта. |
| `--pids-limit 64` | Ограничава общия брой процеси за предотвратяване на fork bombs. |
| `--ulimit nofile=256:256` | Ограничава броя на отворените файлови дескриптори. |
| `--cpus` | Ограничава разпределението на процесорни ядра за контейнер (`CPU_CORES_PER_TASK` / `GPU_CORES_PER_TASK`). |

> **Известно ограничение без критичен характер:** анонимният том за всяко изпълнение, монтиран в `/app` (rw), **няма собствена дискова квота**
> — състезателят може да го запълни, докато достигне дисковото ограничение на хоста. Това е съзнателен
> компромис, приет тъй като паметта, процесорното време, броят на процесите и астрономическото време са ограничени, а
> свободното пространство на `TASK_IMAGES_DIR` (`MIN_BUILD_DISK_GB`) се следи по време на изграждането.

### Структура на персистентното съхранение

Никакви пътища от хоста не се монтират директно (bind-mount) в уъркърите или пясъчните среди. Изображенията на задачите, кешът на HF и
работната област на уъркъра живеят в **именувани томове** на Docker (named volumes), монтирани на фиксирани пътища в контейнера
(`/var/lib/lavbench/task_images`, `/var/lib/lavbench/hf_cache`, `/var/lib/lavbench/workspace`):

- **Docker режим** (`scripts/deploy-worker.sh`): именувани томове `lavbench_task_images`,
  `lavbench_hf_cache`, `lavbench_workspace`, създавани автоматично при внедряване.
- **Compose** (`docker-compose.yml`): `task_images_data`, `workspace_data` плюс споделения
  том `hf_cache`, монтирани на същите пътища в контейнера.
- **CI**: уъркърът за оценяване използва локални за задачата именувани томове със същата структура.
- **Локален micromamba режим**: уъркърът се изпълнява като процес на хоста и използва обикновени директории на хоста
  (`TASK_IMAGES_DIR`, `HF_CACHE_DIR`, `LAVBENCH_WORKSPACE_DIR`) — без участието на Docker томове.

### Пясъчна среда `/app`: анонимен том за всяко изпълнение

Всяко решение получава еднократен анонимен Docker том, монтиран в `/app` (rw). Уъркърът
прехвърля директорията за изпълнение в него чрез `put_archive` преди стартирането на контейнера и
изтегля обратно резултата с `get_archive` след това; томът се премахва заедно с контейнера.
Метаданните на Tar се нормализират за потребителя на пясъчната среда (uid/gid 65534, директории 0777, файлове 0644 + знаменател за изпълнение),
така че процесът без root права да може да чете и пише в `/app`. Това напълно премахва изискането за монтиране на пътища от хоста —
демонът на хоста никога не трябва да разрешава път от страна на уъркъра, така че същият
код на изпълнителя работи при среди с docker, compose, CI и micromamba. Етикетите (`labels.parquet`)
никога не се записват в пясъчната среда; те остават от страната на сървъра.

### Почистване на остарели директории
Работните директории за решения (`LAVBENCH_WORKSPACE_DIR`) обикновено се премахват в блок `finally`,
но прекратен или рестартиран уъркър може да остави некриптирани файлове. Две допълващи се процедури за почистване изтриват всяка
поддиректория от работната област, която не е променяна в продължение на 24 часа:
1. **Стартиране на уъркъра** (tasks.py `_stale_dir_sweep_on_start`, `celeryd_init`, fcntl-сериализирано);
2. **Ежедневен график (beat)** (`task-dir-sweep-daily`).

---

## 5. Пайплайн за изграждане на изображения на задачи и таксономия на грешките при изграждане

Всяка задача поддържа постоянна директория за изграждане в `TASK_IMAGES_DIR/task_{id}/`. Изображението на контейнера се тагова като `lavbench_task_{task_id}`.

### Последователност на изграждане на изображението:
```text
[Base Image Pull] ──> [APT Packages Install] ──> [Pip Requirements Install] ──> [HF Pre-Fetch & Task Files]
```

### Таксономия на грешките при изграждане на изображение (`ERR_IMAGE_BUILD_FAILED`):
1. **Невалидно базово изображение**: Несъществуващ таг или грешка 404/401 при изтегляне от регистъра.
2. **Грешка при откриване на APT пакети**: Сгрешени имена на Ubuntu пакети или липсващи apt хранилища.
3. **Конфликт в Pip зависимостите**: Несъвместими версии на Python библиотеки или липсващи инструменти за компилиране на C/C++ (`build-essential`).
4. **Изтичане на времето за изтегляне / грешка при автентификация в HuggingFace**: Загуба на мрежова връзка, превишаване на лимита от време или липсващ `hf_api_key` за модели с ограничен достъп.
5. **Изчерпване на дисковото пространство**: Свободното дисково пространство на хоста е под `MIN_BUILD_DISK_GB` (лимит от 5 GB).

### Възстановяване от грешки при изграждане и отстраняване на проблеми:
- Неуспешните изграждания или проблеми с обкръжението се записват като **регистрирани проблеми** — списък с машиночитаеми кодове в `task.problem_codes` (напр. `ERR_HF_DOWNLOAD_FAILED`, `ERR_TASK_BUILD_FAILED`, `ERR_BASELINE_FAILED`). Всеки непразен регистър блокира нови решения с `ERR_TASK_NOT_READY` (403) и всяка първопричина се превежда от страната на клиента.
- Регистърът се управлява според жизнения цикъл: съобщените от уъркър грешки при изграждане добавят кодове, успешното изграждане изчиства кодовете от семейството за изграждане, завършването на базовия бележник премахва `ERR_BASELINE_FAILED`, а промените в конфигурацията на обкръжението (базово изображение, apt/pip/HF настройки) изчистват остарелите проблеми от семейството за изграждане.
- Ако заключването за изграждане заседне поради прекъсване на уъркъра, администратор може да го изчисти на хоста на уъркъра с помощната функция от страна на уъркъра `clear_build_lock(task_id)` (`task_modules/image_builder.py`) — например от командния ред на уъркъра. За това няма бутон в потребителския интерфейс или администраторски HTTP маршрут.
- Запазването на съществени промени по задачата (базово изображение, apt/pip/HF настройки, файлове на задачата, код на оценителя) публикува известие `task_rebuild` в Redis; слушателят за преизграждане на уъркъра (`_rebuild_listener`) изтегля отново конфигурацията на задачата и я изгражда наново с `force_rebuild=True`, заобикаляйки бързия път с хеш на конфигурацията. Ресурсите от HuggingFace се преизчисляват спрямо най-новата ревизия (etag повторна валидация, само променени байтове) и изображението се изгражда отново от свежите данни.

### Подмяна на файлове и етикети на задачата (уникално `saved_name`)
Качените ресурсни файлове на задачата (включително `labels.parquet`) се съхраняват под име с префикс UUID
(`saved_name`, с запазено разширение). Тъй като повторното качване на файл със *същото* публично име
ротира `saved_name`, кешът за ресурси от страна на уъркъра — който използва `saved_name` като маркер
за промяна — открива подмяната и ресинхронизира новите байтове в `TASK_IMAGES_DIR/task_{id}/data`
(и в кеша `labels/` само на хоста), а изгражданията на изображения пресъздават новите данни. `update_task` запазва
точно един запис в манифеста за публично файлово име и освобождава подменения файл от диска след
успешно потвърждение.

---

## 6. Архитектура на модула за оценяване

`evaluation_engine.py` поддържа 44 стандартни метрики за оценяване в 12 категории проблеми, заедно с персонализирани скриптове за оценяване (`evaluator.py`).

| # | Категория | Ключове на метриката | Основно предназначение |
| :--- | :--- | :--- | :--- |
| 1 | **Класификация** | `accuracy`, `f1`, `precision`, `recall`, `cohen_kappa`, `matthews_corrcoef` | Класификация с дискретни целеви стойности. |
| 2 | **Вероятностни** | `auc_roc`, `logloss`, `brier_score` | Калибрирани непрекъснати оценки на увереност. |
| 3 | **Регресия** | `rmse`, `mse`, `mae`, `r_squared`, `mape`, `median_ae` | Измерване на грешката при непрекъснати целеви стойности. |
| 4 | **Етикетиране на последователности (NER)** | `seqeval_f1`, `seqeval_precision`, `seqeval_recall` | Класификация на същности на ниво токени. |
| 5 | **Генеративен NLP** | `bleu`, `rouge`, `rouge_l`, `meteor`, `chrf`, `ter` | Превод, резюмиране и генериране на текст. |
| 6 | **Извличащ въпросно-ответен анализ (QA Extractive)** | `exact_match`, `f1` (word-overlap) | Припокриване на токени при разбиране на текст. |
| 7 | **Откриване на обекти (Object Detection)** | `map_50`, `map_75`, `map_50_95`, `recall` (box recall) | Оценяване на IoU и mAP за ограничаващи рамки (bounding box). |
| 8 | **Сегментация** | `mean_iou`, `dice`, `pixel_accuracy` | Оценяване на семантични маски и маски на обекти. |
| 9 | **Ключови точки (Keypoints)** | `oks`, `pck` | Сходство на ключови точки за оценка на позата. |
| 10 | **Качество на изображения** | `psnr`, `ssim` | Метрики за реконструкция и възстановяване на изображения. |
| 11 | **Качество на аудио** | `snr`, `mel_lsd`, `si_sdr` | Качество на обработка на реч и аудио. |
| 12 | **Клъстеризация** | `adjusted_rand_index`, `normalized_mutual_info`, `adjusted_mutual_info`, `v_measure` | Сходство при групиране в клъстери без учител. |
| + | **Извличане на информация (Retrieval)** | `ndcg_k`, `recall_k`, `mrr` | Метрики за извличане на информация и класиране. |
| * | **Персонализирани оценители** | Динамично `METRIC_NAME`, върнато от `evaluator.py` | Персонализирани скриптове за оценяване за специфични домейни (`evaluate(df_sub, df_labels, options)`). |

---

## 7. Архитектура на API типовете и валидацията

```text
Pydantic v2 Schemas + spectree @api.validate Decorators
       │
       ▼
  /apidoc/openapi.json (auto-generated OpenAPI 3.0 spec)
       │
       ▼
  openapi-typescript (npm run generate-api-types)
       │
       ▼
  src/types/api.d.ts (Full TypeScript declaration file)
       │
       ▼
  tsc --noEmit (npm run check-types — validates JSDoc annotations & component props)
```

Спецификацията е достъпна през nginx на `:80/apidoc/openapi.json` (без нужда от порт на бекенд хоста). CI задачата `docker-build` регенерира `api.d.ts` от работещия стек и спира с грешка при разминавания; записите на спецификацията в `docs/source/api/` се обновяват с `make -C docs fetch-spec`. Цялостното поведение (автентификация, матрица на роли, ограничения на честотата, резервни копия, SSE) се тества от `scripts/api_smoke_test.py` спрямо работещия compose стек в CI.

### Стандартизация на грешките (`err()` и `check_error_codes.py`)
Всички отговори за грешки в бекенд API използват `err("ERR_CODE", status_code)`, връщайки `{"error": "<message>", "code": "ERR_CODE"}`. Скриптът `backend/scripts/check_error_codes.py` потвърждава в CI, че всеки код за грешка е регистриран в `DEFAULT_ERROR_MESSAGES` и преведен във локализационните файлове за `en` и `bg`.

---

## 8. Архитектура за поточно предаване в реално време чрез SSE

7 крайни точки в бекенда използват Server-Sent Events (SSE) за телеметрия и поточно предаване на данни в реално време:

| Крайна точка | Поточно предавани данни | Тригерно събитие |
| :--- | :--- | :--- |
| `/api/challenges/<id>/leaderboard/live` | JSON с класацията на състезанието на живо | Пресметнат резултат от решение или ръчно редактиран резултат. |
| `/api/tasks/<id>/submissions/live` | Обновяване на списъка с решения | Добавено ново решение в опашката или промяна на състоянието. |
| `/api/submissions/<id>/logs/live` | Редове от журналите на изпълнението | Изходен поток stdout/stderr на живо от пясъчната среда на уъркъра. |
| `/api/admin/workers/stats/live` | Телеметрия на клъстера от уъркъри | Свързване/прекъсване на уъркър или обновяване на слот. |
| `/api/admin/backups/live` | Списък с архиви на резервни копия | Завършване на автоматично или ръчно резервно копие. |
| `/api/admin/submissions/queue/live` | Състояние на опашката от решения на живо | Събития за добавяне в опашката, потвърждение или отхвърляне. |
| `/api/worker-status/live` | Здраве на клъстера (значка в навигацията) | Периодични сигнали (heartbeats) и промени в състоянието на уъркър. |

Капацитетът на SSE се управлява от две променливи на средата: `SSE_MAX_GLOBAL` (по подразбиране `2000` едновременни връзки за цялата платформа) и `SSE_MAX_PER_USER` (по подразбиране `15` за клиент), като и двете могат да бъдат презаписани през `.env`.

---

## 9. Архитектура за съхранение на автоматични и ръчни резервни копия

| Тип резервно копие | Честота на задействане | Политика за съхранение | Управление и API ограничения |
| :--- | :--- | :--- | :--- |
| **Автоматично резервно копие** | На всеки **20 минути** по време на активни състезания; на всеки **6 часа** при престой. | Пази **6-те най-нови** резервни копия. По-старите автоматични копия се изтриват автоматично. | Управлява се от системата (`auto_YYYYMMDD_HHMMSS.tar.gz`). Не може да се изтрива ръчно през API (връща HTTP 403). |
| **Ръчно резервно копие** | Задейства се при поискване чрез бутона **"Force Backup Now"**. | Съхранява се **завинаги**. Никога не се изтрива автоматично от процедурите за съхранение. | Управлява се от администратора (`manual_YYYYMMDD_HHMMSS.tar.gz`). Може да се изтегля или изтрива през администраторския панел. |

Всеки архив на резервно копие съдържа пълен дъмпови файл на PostgreSQL базата данни (`pg_dump`), заедно с компресирани ресурси от `uploads/` във формат `.tar.gz`.

---

## 10. Разпределение и ограничаване на хардуерните ресурси на уъркърите

По време на първоначалната настройка (`make setup-worker`), уъркърите проверяват общия брой процесорни ядра (`nproc`), RAM паметта (`/proc/meminfo`) и графичните процесори (`nvidia-smi`), заделяйки 1 CPU ядро и 4 GB RAM за системни нужди.

### Формула за ограничаване на RAM паметта по време на изпълнение:
```text
budget_mb = (GPU_RAM_PER_TASK_GB if task.gpu_required else CPU_RAM_PER_TASK_GB) * 1024

if task_ram <= budget_mb:
    use task_ram as-is
elif task_ram <= budget_mb * RAM_CLAMP_FACTOR (1.05):
    clamp container memory to budget_mb (log warning)
else:
    reject task → Celery retry → dead-letter queue (/api/admin/dead-letters)
```

При сигнал `worker_ready`, уъркърите записват своите хардуерни спецификации в клиента за координация на Redis (`worker_spec:<hostname>`, с TTL от 24 часа), които се предоставят чрез `/api/admin/workers/stats` и се показват в навигационната лента на администратора. Регистрацията на уъркър е изцяло базирана на сигнали — вече не съществува отделна задача за регистрация.
