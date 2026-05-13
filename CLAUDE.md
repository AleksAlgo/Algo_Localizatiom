# Jerome 1.0 — Translation Agent

## Назначение

Веб-агент для перевода корпоративных документов из Google Drive.
Переводит файлы через Claude Sonnet, выполняет ревью через Claude Opus,
выдаёт отчёт о качестве по метрике MQM.

---

## Основа проекта

Jerome 1.0 строится на базе Translation QA Benchmark Agent v0.2 (es_benchmark).

### Переиспользуемые модули из es_benchmark

```
translation-qa-agent/scripts/
├── llm_clients.py       ← клиент Anthropic API
├── translator.py        ← батчевый перевод, batch_size=20
├── qa_judge.py          ← MQM-судья, batch_size=25
├── reviewer.py          ← Opus-ревью, batch_size=15
├── report_generator.py  ← markdown QA-отчёты
├── file_handlers.py     ← PPTX/DOCX extract + write (расширить: XLIFF)
└── reference/qa_criteria.json  ← 32 типа ошибок MQM
```

---

## Структура проекта

```
jerome/
├── CLAUDE.md                  ← этот файл
├── app.py                     ← Flask/FastAPI веб-сервер
├── jerome_engine.py           ← основной движок (оркестратор)
├── drive_client.py            ← Google Drive интеграция
├── xliff_handler.py           ← парсер/сборщик XLIFF
├── static/
│   └── index.html             ← веб-интерфейс (одна страница)
├── service_account.json       ← ключ сервисного аккаунта (не в git!)
└── requirements.txt
```

---

## Языковые пары

Фиксированное выпадающее меню:

| Отображение | src_lang | tgt_lang |
|---|---|---|
| Русский → Английский | ru | en |
| Английский → Испанский | en | es |

---

## Модели

| Роль | Модель | model_id |
|---|---|---|
| Переводчик | Claude Sonnet | `claude-sonnet-4-20250514` |
| Ревьюер | Claude Opus | `claude-opus-4-20250514` |
| QA-судья | Claude Sonnet | `claude-sonnet-4-20250514` |

Все вызовы — через прямой Anthropic API (не OpenRouter).

---

## Поддерживаемые форматы

| Формат | Чтение | Запись | Примечание |
|---|---|---|---|
| .docx | ✅ | ✅ | python-docx |
| .pptx | ✅ | ✅ | python-pptx |
| .xliff | ✅ | ✅ | кастомный парсер xliff_handler.py |
| Google Doc | ✅ | ✅ | экспорт→перевод→загрузка как .docx |
| Google Presentation | ✅ | ✅ | экспорт→перевод→загрузка как .pptx |

---

## Лимит объёма

- Максимум: **6000 слов суммарно** по всем файлам в папке
- Подсчёт: после скачивания и извлечения текста из всех файлов
- При превышении: показать список файлов с объёмом каждого, живой счётчик

### Поведение при превышении лимита

1. Агент скачивает все файлы из исходной папки
2. Извлекает текст и считает слова по каждому файлу
3. Если суммарный объём > 6000 слов — **не начинать перевод**
4. Показать таблицу:

```
Файл                    Слов
────────────────────────────
lesson_01.docx          1240
lesson_02.pptx          2100
lesson_03.docx          3800   ← превышение здесь
────────────────────────────
Итого выбрано:          7140 / 6000  [красный счётчик]
```

5. Пользователь снимает галочки с файлов
6. Счётчик обновляется в реальном времени
7. Кнопка "Перевести" активируется когда итого ≤ 6000
8. Сообщение при превышении:

```
К сожалению, свыше 6000 слов перевести невозможно.
Удалите из папки лишние файлы или обратитесь в отдел локализации.
```

---

## Google Drive интеграция

### Аутентификация

- Метод: **сервисный аккаунт**
- Email: `googlesheetshelper@sunlit-unison-494214-g0.iam.gserviceaccount.com`
- Ключ: `service_account.json` в корне проекта
- Библиотека: `google-auth`, `google-api-python-client`

### Scope

```python
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',   # читать исходную папку
    'https://www.googleapis.com/auth/drive.file'        # писать в конечную папку
]
```

### Требование к папкам

Обе папки Drive должны быть расшарены на email сервисного аккаунта:
- Исходная папка: право **Viewer**
- Конечная папка: право **Editor**

### Логика работы с Drive

```
drive_client.py:
  list_folder(folder_id)        → список файлов с метаданными
  download_file(file_id, fmt)   → скачать файл (или экспортировать гугл-формат)
  upload_file(folder_id, path)  → загрузить файл в конечную папку
  get_folder_id_from_url(url)   → извлечь folder_id из ссылки Drive
```

### Извлечение folder_id из URL

Пользователь вставляет ссылку вида:
```
https://drive.google.com/drive/folders/1ABC...XYZ
```
Агент извлекает `1ABC...XYZ` как folder_id.

---

## Веб-интерфейс (index.html)

### Элементы страницы

```
[Логотип Jerome 1.0]

Языковая пара:     [▼ Русский → Английский]

Исходная папка:    [https://drive.google.com/drive/folders/...]  [Проверить]

Конечная папка:    [https://drive.google.com/drive/folders/...]

[Начать перевод]
─────────────────────────────────────────────
Прогресс: [████████░░] 4/5 файлов

Файл                  Слов    Статус
─────────────────────────────────────────
lesson_01.docx        1240    ✅ Переведён
lesson_02.pptx         890    ✅ Переведён
lesson_03.docx        2100    🔄 Перевод...
─────────────────────────────────────────
[Скачать отчёт QA]
```

### При превышении лимита (режим выбора)

```
⚠️ Суммарный объём превышает 6000 слов.

  ☑ lesson_01.docx        1240 слов
  ☑ lesson_02.pptx         890 слов
  ☐ lesson_03.docx        3800 слов  ← снята галочка

Выбрано: 2130 / 6000 слов  [зелёный]

[Перевести выбранные]
```

---

## Pipeline перевода (jerome_engine.py)

```
для каждого выбранного файла:
  1. скачать из Drive (drive_client.download_file)
  2. извлечь сегменты (file_handlers / xliff_handler)
  3. перевести батчами (translator.py → Sonnet)
  4. QA-оценка (qa_judge.py → Sonnet)
  5. Opus-ревью перевода (reviewer.py → Opus)
  6. собрать файл (file_handlers / xliff_handler)
  7. загрузить в конечную папку (drive_client.upload_file)
  8. сгенерировать QA-отчёт (report_generator.py)

итого:
  9. сводный отчёт по всем файлам
```

---

## Метрика качества: MQM

Унаследована из es_benchmark без изменений.

**Quality Score = Σ штрафов / (кол-во слов / 1000)**

| Score | Уровень | Решение |
|:---:|---|:---:|
| 0–9 | Excellent | PASS |
| 10–19 | Good | PASS |
| 20–29 | Acceptable | PASS (условный) |
| 30–49 | Poor | FAIL |
| ≥ 50 | Unacceptable | FAIL |
| любой с Critical | Critical errors present | FAIL |

**Веса:** Critical=10, Major=5, Minor=1, Neutral=0

---

## Отчёт о качестве

Генерируется для каждого файла и сводный по всем файлам.

### Содержание отчёта

```
# Отчёт Jerome 1.0 — lesson_01.docx
Дата: 2026-05-12
Языковая пара: ru → en
Модель перевода: claude-sonnet-4-20250514
Модель ревью: claude-opus-4-20250514

## Результат
Слов: 1240
MQM Score: 14.2 — Good ✅

## Ошибки по категориям
accuracy:    2 major, 3 minor
fluency:     1 major, 5 minor
terminology: 0

## Детали ошибок
...

## Ревью Opus
...
```

---

## Безопасность

- `service_account.json` — в `.gitignore`, никогда не в репозиторий
- Переменная окружения: `ANTHROPIC_API_KEY`
- Доступ к интерфейсу: только внутри корпоративной сети (Phase 2 — Google OAuth @alg.team)

---

## Python-зависимости

```
anthropic
google-auth
google-auth-oauthlib
google-api-python-client
python-pptx
python-docx
flask
openpyxl
lxml          # для XLIFF парсинга
```

Установка:
```
pip install anthropic google-auth google-auth-oauthlib google-api-python-client python-pptx python-docx flask openpyxl lxml
```

Python: 3.11

---

## Переменные окружения

```powershell
$env:ANTHROPIC_API_KEY    = "sk-ant-..."
$env:PYTHONIOENCODING     = "utf-8"
```

---

## Запуск

```powershell
$py = "C:\Users\Alexandre\AppData\Local\Programs\Python\Python311\python.exe"
cd C:\Users\Alexandre\Downloads\jerome
& $py app.py
# Открыть браузер: http://localhost:5000
```

---

## Roadmap

| Версия | Что добавить |
|---|---|
| 1.0 | Сервисный аккаунт, базовый UI, 5 форматов |
| 1.1 | Google OAuth (@alg.team), логи пользователей |
| 1.2 | Глоссарий, настраиваемый лимит слов |
| 2.0 | Мультиязычность, очередь задач, история переводов |

---

## Известные ограничения v1.0

- Сервисный аккаунт требует ручного расшаривания каждой папки
- XLIFF: только стандарт 1.2 и 2.0
- Google Docs/Slides: потеря части форматирования при экспорте в docx/pptx
- Один файл > 6000 слов — не переводится (пользователь обращается в отдел локализации)
