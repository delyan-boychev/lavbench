# Архитектура и инфраструктура на системата LavBench

## 1. Преглед на системата

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
| **Frontend** | React 19 + Vite + Vanilla/Tailwind CSS | SPA с обновявания на живо чрез SSE, i18n (en/bg), валидация на JSDoc `@type` (`tsc --noEmit`). |
| **API Server** | Flask 3.1 + Gunicorn + gevent + spectree | REST API крайни точки (endpoints), валидация на заявки/отговори с Pydantic v2, поточно предаване на събития чрез SSE. |
| **Primary Database** | PostgreSQL 15 | Потребители, състезания, етапи, задачи, решения, одитни журнали (`AuditLog`). |
| **Cache & Broker** | Redis | Брокер на задачи за Celery + **координиращ клиент** за цялото споделено състояние между машините: SSE pub/sub fan-out, регистър на спецификациите на работниците (`worker_spec:<hostname>`), резервен ключ за решения (submission fallback key), съвкупност от променени състезания (dirty-challenges set), опашка за неполучени съобщения (dead-letter queue), GPU/build заключения (locks). |
| **Dedicated Cache** | Redis (DB 1, `noeviction`, no persistence) | Частен кеш, достъпен само за сървъра: кешове на класациите, разпределени заключения (locks), броячи за ограничаване на честотата на заявките (rate-limit counters) и черен списък за JWT токени (`CACHE_REDIS_URL`). Вътрешен контейнер — без порт към хоста; външните работници никога не получават този URL адрес. |
| **Task Queue** | Celery 5.4 | Асинхронно изпълнение на задачи (оценяване на решения, компилиране на изображения, резервни копия на базата данни). |
| **Scheduler** | Celery Beat | Периодични задачи (наблюдател/watchdog за блокирали решения, автоматизиран график за резервни копия). |
| **Worker Nodes** | Celery Evaluation Worker | Работници **само за оценяване**, използващи `cpu_queue`; изпълняват кода на състезателя в паралелни (sibling) Docker контейнери в пясъчна среда (`deploy-worker.sh` / `worker.env`). |

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

## 4. Пайплайн за решения и сигурност чрез изолация в пясъчна среда

```text
1. User uploads .ipynb → POST /api/challenges/<id>/parse-notebook
2. User selects code cells → POST /api/challenges/<id>/submit
3. Server: Pre-execution AST validation (IPython magic stripping, banned_imports check) → rate limit check → creates Submission → dispatches Celery evaluation job
4. Worker Node: picks up job → ensures task Docker image (lavbench_task_<id>) is compiled → mounts submission.parquet & hidden labels.parquet
5. Hardened Sandbox Container: launches execution with zero-trust security parameters
6. Competitor Code: executes inside container → writes submission.parquet output
7. Worker Evaluation Engine: evaluates submission.parquet against labels.parquet (or runs evaluator.py) → updates Submission status & scores → publishes SSE event → invalidates leaderboard cache
```

### Параметри за изолация на контейнера в пясъчна среда

Кодът на състезателя се изпълнява в Docker контейнер с нулево доверие (zero-trust) със стриктни ограничения на ядрата (kernel capabilities) на Linux:

| Параметър | Цел и гаранция за сигурност |
| :--- | :--- |
| `--network none` | Напълно изключва мрежата на контейнера — предотвратява изтичане на данни и външни сокет повиквания. |
| `--cap-drop ALL` | Премахва всички възможности (capabilities) на Linux ядрото — блокира необработени сокети (raw sockets), `mount()`, `ptrace()` и ескалация на привилегии. |
| `--read-only` | Монтира кореновата файлова система само за четене — кодът на състезателя не може да променя системни бинарни файлове или библиотеки. |
| `--no-new-privileges` | Предотвратява ескалация на привилегиите на процеса чрез SUID бинарни файлове. |
| `--tmpfs /tmp:noexec,nosuid,size=128m` | Временна директория в паметта с ограничен размер, която не може да изпълнява бинарни файлове или да консумира дисково пространство на хоста. |
| `--memory-swap` = RAM Limit | Изключва суоп (swap) паметта — гарантира незабавно прекратяване на процеса от ядрото при превишаване на лимита на RAM (OOM kill). |
| `--pids-limit 64` | Ограничава общия брой процеси за предотвратяване на форк бомби (fork bombs). |
| `--ulimit nofile=256:256` | Ограничава броя на отворените файлови дескриптори. |
| `--cpus` | Ограничава заделянето на процесорни ядра за всеки контейнер (`CPU_CORES_PER_TASK` / `GPU_CORES_PER_TASK`). |

> **Известен некритичен проблем:** монтирането тип bind mount на `/app` (rw) **няма собствена дискова квота** —
> състезател може да го запълни до достигане на дисково ограничение на хоста. Това е съзнателен компромис,
> приет тъй като паметта, процесорът, броят PID процеси и времето за изпълнение са ограничени, а свободното
> пространство в `TASK_IMAGES_DIR` (`MIN_BUILD_DISK_GB`) се следи по време на изграждане.

### Почистване на остарели директории (Stale-Dir Sweep)
Работните директории за решения (`LAVBENCH_WORKSPACE_DIR`) обикновено се премахват в блок `finally`,
но прекратен или рестартиран работник може да остави нешифрован текст (plaintext) след себе си. Две допълващи се процедури за почистване изтриват всяка поддиректория на работната област, която не е променяна през последните 24 часа:
1. **При стартиране на работник** (tasks.py `_stale_dir_sweep_on_start`, `celeryd_init`, сериализирано чрез fcntl);
2. **Ежедневен периодичен процес (Daily beat)** (`task-dir-sweep-daily`).

---

## 5. Пайплайн за изграждане на изображения за задачи и таксономия на грешките при изграждане

Всяка задача поддържа персистентна директория за изграждане в `TASK_IMAGES_DIR/task_{id}/`. Изображението на контейнера има таг `lavbench_task_{task_id}`.

### Последователност на изграждане на изображението:
```text
[Base Image Pull] ──> [APT Packages Install] ──> [Pip Requirements Install] ──> [HF Pre-Fetch & Task Files]
```

### Таксономия на грешките при изграждане на изображение (`ERR_IMAGE_BUILD_FAILED`):
1. **Невалидно базово изображение**: Несъществуващ таг или грешка 404/401 при изтегляне (pull) от регистъра.
2. **Грешка при разрешаване на APT**: Грешно изписани имена на Ubuntu пакети или липсващи apt хранилища.
3. **Конфликт в средите/зависимостите на Pip**: Несъвместими версии на Python библиотеки или липсващи C/C++ инструменти за компилиране (`build-essential`).
4. **Превишено време за изтегляне / Грешка при автентификация в HuggingFace**: Мрежово прекъсване, превишен лимит на времето или липсващ `hf_api_key` за модели с ограничен достъп (gated models).
5. **Изчерпване на дисковото пространство**: Свободното дисково пространство на хоста е под `MIN_BUILD_DISK_GB` (лимит от 5 GB).

### Възстановяване от грешки при изграждане и отстраняване на неизправности:
- Сривовете при изграждане/среда се записват като **регистър на проблемите** — списък от машинно четими кодове в `task.problem_codes` (напр. `ERR_HF_DOWNLOAD_FAILED`, `ERR_TASK_BUILD_FAILED`, `ERR_BASELINE_FAILED`). Всеки непразен регистър блокира нови решения с `ERR_TASK_NOT_READY` (403) и всяка първопричина се превежда от страната на клиента.
- Регистърът се управлява според жизнения си цикъл: докладваните от работник грешки при изграждане добавят кодове, успешно изграждане изчиства кодовете от семейството на изграждането, завършването на базовия бележник премахва `ERR_BASELINE_FAILED`, а промените в конфигурацията на средата (базово изображение, apt/pip/HF настройки) изчистват остарелите проблеми от семейството на изграждането.
- Ако заключване за изграждане (build lock) остане блокирано поради прекъсване на работник, администратор може да го изчисти на хоста на работника с помощната функция от страната на работника `clear_build_lock(task_id)` (`task_modules/image_builder.py`) — напр. от команден ред (shell) на работника. За това няма бутон в потребителския интерфейс или администраторски HTTP маршрут.
- Запазването на семантични промени по задачата (базово изображение, apt/pip/HF настройки, файлове на задачата, код на оценителя/evaluator) публикува известие в Redis `task_rebuild`; слушателят за повторно изграждане на работника (`_rebuild_listener`) изтегля отново конфигурацията на задачата и я изгражда наново с `force_rebuild=True`, прескачайки бързия път с хеш на конфигурацията. Ресурсите от HuggingFace се проверяват отново спрямо най-новата версия (etag превалидация, само променените байтове) и изображението се изгражда наново от свежи данни.

### Замяна на файлове и етикети на задача (уникално `saved_name`)
Качените ресурсни файлове на задачата (включително `labels.parquet`) се съхраняват под `saved_name`
с UUID префикс (запазвайки разширението). Тъй като повторното качване на файл със *същото* публично файлово име
ротира `saved_name`, кешът на ресурси от страната на работника — който използва `saved_name` като маркер
за промяна — открива замяната и синхронизира отново новите байтове в `TASK_IMAGES_DIR/task_{id}/data`
(и кеша `labels/`, достъпен само за хоста), а изгражданията на изображения вграждат наново свежите данни. `update_task` поддържа
точно по един запис в манифеста за всяко публично файлово име и освобождава заменения файл от диска след успешно потвърждение (commit).

---

## 6. Архитектура на модула за оценяване

`evaluation_engine.py` поддържа 44 стандартни метрики за оценяване в 12 категории проблеми, заедно с персонализирани скриптове за оценяване (`evaluator.py`).

| # | Категория | Ключове на метрики | Основно предназначение |
| :--- | :--- | :--- | :--- |
| 1 | **Класификация** | `accuracy`, `f1`, `precision`, `recall`, `cohen_kappa`, `matthews_corrcoef` | Класификация на дискретна целева променлива. |
| 2 | **Вероятностни** | `auc_roc`, `logloss`, `brier_score` | Калибрирани непрекъснати оценки на увереността. |
| 3 | **Регресия** | `rmse`, `mse`, `mae`, `r_squared`, `mape`, `median_ae` | Измерване на грешката при непрекъсната целева променлива. |
| 4 | **Последователно етикетиране (NER)** | `seqeval_f1`, `seqeval_precision`, `seqeval_recall` | Класификация на същности на ниво токен. |
| 5 | **Генеративен NLP** | `bleu`, `rouge`, `rouge_l`, `meteor`, `chrf`, `ter` | Превод, резюмиране и генериране на текст. |
| 6 | **Екстрактивни въпроси и отговори (QA)** | `exact_match`, `f1` (word-overlap) | Припокриване на токени при разбиране на текст. |
| 7 | **Откриване на обекти** | `map_50`, `map_75`, `map_50_95`, `recall` (box recall) | Оценяване на обхващащи рамки (bounding box) чрез IoU и mAP. |
| 8 | **Сегментация** | `mean_iou`, `dice`, `pixel_accuracy` | Оценяване на маски за семантична и екземплярна сегментация. |
| 9 | **Ключови точки (Keypoints)** | `oks`, `pck` | Сходство на ключови точки на обекти за оценка на позата. |
| 10 | **Качество на изображения** | `psnr`, `ssim` | Метрики за реконструкция и възстановяване на изображения. |
| 11 | **Качество на аудио** | `snr`, `mel_lsd`, `si_sdr` | Качество на обработка на реч и аудио. |
| 12 | **Клъстеризация** | `adjusted_rand_index`, `normalized_mutual_info`, `adjusted_mutual_info`, `v_measure` | Сходство при неконтролирано групиране в клъстери. |
| + | **Извличане на информация (Retrieval)** | `ndcg_k`, `recall_k`, `mrr` | Метрики за извличане на информация и ранглиста. |
| * | **Персонализирани оценители** | Dynamic `METRIC_NAME` returned by `evaluator.py` | Персонализирани домейн-специфични скриптове за оценяване (`evaluate(df_sub, df_labels, options)`). |

---

## 7. Пайплайн за API типове и архитектура за валидация

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

Спецификацията е достъпна през nginx на `:80/apidoc/openapi.json` (без нужда от порт на бекенд хоста). CI задачата `docker-build` генерира отново `api.d.ts` от работещия стек и завършва с грешка при разминаване; записаните снимки (snapshots) на спецификацията в `docs/source/api/` се обновяват с `make -C docs fetch-spec`. Поведението от край до край (автентификация, матрица на ролите, лимити на честотата на заявките, резервни копия, SSE) се тества от `scripts/api_smoke_test.py` спрямо работещия compose стек в CI.

### Стандартизация на грешките (`err()` и `check_error_codes.py`)
Всички грешки в бекенд API използват `err("ERR_CODE", status_code)`, връщайки `{"error": "<message>", "code": "ERR_CODE"}`. Скриптът `backend/scripts/check_error_codes.py` валидира в CI, че всеки код за грешка е регистриран в `DEFAULT_ERROR_MESSAGES` и е преведен във файловете за локализация за `en` и `bg`.

---

## 8. Поточно предаване в реално време чрез SSE архитектура

7 бекенд крайни точки използват Server-Sent Events (SSE) за телеметрия и поточно предаване на данни в реално време:

| Крайна точка | Предавани данни | Задействащо събитие |
| :--- | :--- | :--- |
| `/api/challenges/<id>/leaderboard/live` | Live Challenge Leaderboard JSON | Изчислен резултат на решението или ръчно редактиран резултат. |
| `/api/tasks/<id>/submissions/live` | Submission List Updates | Добавено ново решение в опашката или промяна на състоянието. |
| `/api/submissions/<id>/logs/live` | Execution Log Lines | Изходен stdout/stderr лог в реално време от пясъчната среда на работника. |
| `/api/admin/workers/stats/live` | Worker Cluster Telemetry | Свързване/прекъсване на работник или обновяване на слот. |
| `/api/admin/backups/live` | Backup Archives List | Завършване на автоматично или ръчно резервно копие. |
| `/api/admin/submissions/queue/live` | Live Submission Queue State | Събития за добавяне в опашката, потвърждаване или отхвърляне. |
| `/api/worker-status/live` | Cluster Health (Navbar Badge) | Периодични сигнали (heartbeats) от работника и промени в състоянието. |

Капацитетът за SSE се управлява от две променливи на средата: `SSE_MAX_GLOBAL` (по подразбиране `2000` едновременни връзки за цялата платформа) и `SSE_MAX_PER_USER` (по подразбиране `15` на клиент), като и двете могат да бъдат презаписани през `.env`.

---

## 9. Архитектура за съхранение на автоматични и ръчни резервни копия

| Тип резервно копие | Честота на задействане | Политика за съхранение | Управление и API ограничения |
| :--- | :--- | :--- | :--- |
| **Автоматично резервно копие** | На всеки **20 минути** по време на активни състезания; на всеки **6 часа** при липса на активност. | Запазва **6-те най-нови** резервни копия. По-старите автоматични копия се изтриват автоматично. | Управлява се от системата (`auto_YYYYMMDD_HHMMSS.tar.gz`). Не може да се изтрива ръчно през API (връща HTTP 403). |
| **Ръчно резервно копие** | Задейства се при поискване чрез бутона **"Force Backup Now"**. | Съхранява се **за неопределено време**. Никога не се изтрива автоматично от процедурите за почистване. | Управлява се от администратора (`manual_YYYYMMDD_HHMMSS.tar.gz`). Достъпно за изтегляне или изтриване през Администраторския панел. |

Всеки архив с резервно копие съдържа пълен дъмпове на базата данни PostgreSQL (`pg_dump`) заедно с компресирани ресурси от `uploads/` във формат `.tar.gz`.

---

## 10. Бюджетиране и ограничаване (Clamping) на хардуера на работника

По време на първоначалната настройка (`make setup-worker`), работниците проверяват общия брой процесорни ядра (`nproc`), RAM паметта (`/proc/meminfo`) и графичните процесори (`nvidia-smi`), като резервират 1 процесорно ядро и 4 GB RAM за системни нужди.

### Формула за ограничаване (clamping) на RAM паметта по време на изпълнение:
```text
budget_mb = (GPU_RAM_PER_TASK_GB if task.gpu_required else CPU_RAM_PER_TASK_GB) * 1024

if task_ram <= budget_mb:
    use task_ram as-is
elif task_ram <= budget_mb * RAM_CLAMP_FACTOR (1.05):
    clamp container memory to budget_mb (log warning)
else:
    reject task → Celery retry → dead-letter queue (/api/admin/dead-letters)
```

При сигнал `worker_ready` работниците записват своите хардуерни спецификации в координиращия Redis клиент (`worker_spec:<hostname>`, TTL 24 часа), които се предоставят чрез `/api/admin/workers/stats` и се показват в навигационната лента на администратора. Регистрирането на работници се управлява изцяло от сигнали — вече не съществува отделна задача за регистрация.
