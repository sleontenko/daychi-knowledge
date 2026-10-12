# Daychi Knowledge

Приватный проект подготовки знаний школы: источники, оцифровка, расшифровки,
конспекты, темы, словарь, редактура и независимая проверка.

Приложение, сайт, интерфейс вики и серверный API находятся в
[Daychi](https://github.com/sleontenko/daychi). Этот репозиторий готовит пакеты
для существующего API; отдельный сервер и новый API не вводятся.

## Начало работы

Для Claude, Codex и человека: [алгоритм совместной работы](docs/collaboration-workflow.md).
Прочитать AGENTS.md; Claude также получает CLAUDE.md. Получить у координатора
свежую очередь и резервирование до работы с содержимым. Финальная приёмка
сейчас у владельца (`sleontenko`); права будущего агента-приёмщика ещё не назначены.

Свежая read-only сверка **09.10.2026**: 1350 строк реестра, 476 конспектов
и 1428 цитат в production; расхождений по импорту нет. 45 опубликованных
конспектов ожидают независимой проверки. 874 не импортированы; это источники
и контейнеры, а не 874 готовых или уникальных занятия. Очередь строится заново
из приватного реестра и API, эти числа не разрешают брать конкретное задание.

```sh
git clone https://github.com/sleontenko/daychi-knowledge.git
cd daychi-knowledge
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_repository.py
```

Для существующих команд сохранён namespace `scripts.*`: запускать их из корня
этого репозитория. Команды и протоколы — в [процессе](docs/wiki-production-pipeline.md),
[инструкции участника](docs/wiki-contributor-pipeline.md),
[реестре](docs/wiki-team-pipeline.md), [плане](docs/wiki-work-plan.md)
и [семантическом протоколе](docs/wiki-semantic-pipeline.md).
Для исторических аудиоматериалов: [архивные коллекции и подготовка](docs/wiki-archive-collections.md).
Для структурированных статей: [совместимый контракт и импорт](docs/daychi-article-contract.md),
[исправление трёх статей](docs/wiki-updates/2026-10-11-structured-article-repair.md).
История full-source пилота: [обновлённый алгоритм](docs/wiki-article-pilot-protocol.md),
[предложение расширенного контракта](docs/daychi-article-contract-proposal.md)
и [публикация текстов трёх пробных статей](docs/wiki-updates/2026-10-09-article-pilot.md).
[Разбор потери структуры](docs/wiki-updates/2026-10-09-article-format-review.md):
тексты импортированы, но согласованный формат статьи и смысловые переходы
не реализованы; этот результат требует исправления.
Модели ASR устанавливаются отдельно по `scripts/wiki-pipeline-requirements.txt`
в существующее совместимое окружение Apple Silicon. Обычные тесты их не требуют.

## Данные и публикация

`data/` — локальная приватная рабочая область, исключённая из Git вместе с
аудио, видео, PDF, Excel, SQLite, receipts и credentials. Git хранит код,
протоколы и синтетические тесты; приватность репозитория не отменяет это правило.
Основной реестр — `data/wiki-workspace/outputs/2026-10-02/wiki-materials.xlsx`.
Не создавать второй авторитетный реестр и не пересобирать поверх ручных правок.

Координатор выдаёт задания, принимает независимый review, валидирует и импортирует
пакет. `--apply` означает запись на сервер и требует разрешения на конкретную
партию. Сам перенос репозитория не разрешает новый production-импорт.
Команды импорта также требуют coordinator workflow database, assignment_id
и durable receipt; без --apply прежняя локальная валидация сохранена.
Конспекты сохраняют статус `source_checked_draft`; он не означает одобрения
преподавателем. Редакторам не нужны административные credentials.

## Граница с Daychi

[Контракт v1](docs/daychi-content-contract.md) сохраняет ID, revisions, hashes,
статусы, payload и owner endpoints. Локальные модели в `daychi_contracts/`
не зависят от `practice_api`; сервер остаётся авторитетным валидатором.
[Запись переноса](docs/repository-migration-2026-10-09.md) и
`migration/source-manifest.json` фиксируют происхождение файлов, в том числе
сохранённые незакоммиченные изменения. История исходного репозитория не переписана.
Оставшиеся [PR #4–7](docs/legacy-pr-reconciliation-2026-10-09.md) согласованы
с разделением; уникальные исторические варианты сохранены с per-file hashes.
