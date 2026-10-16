# Daychi Knowledge

Работать с оцифровкой и редакционным пайплайном здесь, а не в Daychi.
Перед работой прочитать README.md, docs/wiki-production-pipeline.md,
docs/wiki-contributor-pipeline.md, docs/wiki-team-pipeline.md и docs/wiki-work-plan.md.
Сначала выполнить docs/collaboration-workflow.md: свежая очередь, координаторское
резервирование, независимый review и одна финальная приёмка.
Смысловые страницы также требуют docs/wiki-semantic-pipeline.md.

- Git хранит инструменты, документацию и синтетические fixtures. Не коммитить
  корпус, расшифровки, реестр, рабочие базы, receipts, сессии и credentials.
- Основной реестр — приватный `data/wiki-workspace/outputs/2026-10-02/wiki-materials.xlsx`.
  Объединять по стабильным ID, сохранять исходные периоды, назначения и правки.
- После партии обновлять docs/wiki-work-plan.md: выполнено/осталось, фактическое
  время, доступный usage, оценки и следующий объём. Не переписывать прошлые факты.
- Редактор и проверяющий независимы. Данные и импорт остаются у координатора.
  Не приписывать слушание, измеренную точность или одобрение преподавателя.
- Не начинать работу из старого прогресса/PR. Нужен coordinator-issued assignment_id;
  не создавать свой авторитетный журнал. Финальный ответственный сейчас sleontenko.
  SQLite хранит новые резервирования и решения, XLSX остаётся каталогом/ручным реестром.
- Не освобождать занятые задачи по таймауту. accepted не означает published;
  --apply требует отдельного разрешения, accepted hash и publication QA после receipt.
- Приложение, сайт, reader/граф и серверный API принадлежат `sleontenko/daychi`.
  Форматы импорта определены в docs/daychi-content-contract.md.
- Любые production imports, deploy и releases требуют отдельного явного разрешения.
  Разделение репозиториев не является таким разрешением.
- Перед commit/push проверить git status, staged diff и scripts/check_repository.py.
  PR title/body — на английском. Тесты: `python -m pytest -q`.
- Не копировать server/storage в этот репозиторий. Изменения wire contract
  согласовывать с Daychi, сохраняя совместимость действующей версии.

## Workshop collaboration

Use [.agents/skills/collaborate/SKILL.md](.agents/skills/collaborate/SKILL.md)
at session startup, before boundary changes, and when coordinating with Workshop.

Knowledge prepares content packages for Daychi’s import APIs. Knowledge owns source
preparation, editorial review and import tooling; Daychi owns import definitions,
storage, access control and readers.

See the [content contract](https://github.com/sleontenko/daychi-knowledge/blob/e4006807c3adaa373ad3a6f63396d0a2eaea66ef/docs/daychi-content-contract.md)
and [article contract](https://github.com/sleontenko/daychi-knowledge/blob/e4006807c3adaa373ad3a6f63396d0a2eaea66ef/docs/daychi-article-contract.md)
for the shared definitions. Local import tools are under `scripts/`; contract
mirrors are in `daychi_contracts/`.
