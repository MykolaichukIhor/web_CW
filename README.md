# My image app

## Повний опис архітектури та взаємодії компонентів

---

## 1. DJANGO запити

### Django як основа
Весь додаток побудований на стандартному Django MVT (Model-View-Template). Кожна сторінка проходить через Django URL dispatcher → View → Template rendering.

**URL конфігурація (не показана в коді, але логіка зрозуміла з шаблонів):**
- `gallery/` → основна галерея
- `photo/<id>/` → перегляд одного фото
- `edit/<id>/` → редагування
- `upload/` → завантаження нового фото
- `delete/<id>/` → видалення
- `set_language/` → стандартний Django i18n URL для зміни мови
- `login/`, `signup/`, `logout/` → аутентифікація

Кожен URL веде до Django View, який отримує `request` об'єкт. View витягує дані з БД через Django ORM, формує `context` (словник змінних), і передає в шаблон.

### Django Template Engine
Шаблони використовують Django Template Language (DTL):
- `{% load i18n %}` — завантажує модуль інтернаціоналізації
- `{% trans "текст" %}` — перекладає рядок на поточну мову
- `{% url 'name' %}` — генерує URL за іменем маршруту
- `{% csrf_token %}` — вставляє приховане поле з токеном для захисту від CSRF атак
- `{{ photo.description }}` — виводить значення змінної
- `{{ photo.description|default:"fallback" }}` — фільтр default, якщо значення пусте
- `{% for photo in photos %}` — цикл по queryset
- `{% if condition %}` — умовний рендеринг
- `{% get_current_language as LANGUAGE_CODE %}` — отримує код поточної мови
- `{% get_available_languages as LANGUAGES %}` — список доступних мов з settings.py

### Контекст даних
View передає в шаблон дані через context dictionary. Основні об'єкти контексту:

1. **`photo`** — одиночний об'єкт моделі Photo
2. **`photos`** — queryset об'єктів Photo (може бути відфільтрований за категорією, пошуком, датою)
3. **`categories`** — queryset об'єктів Category
4. **`form`** — Django Form об'єкт (для upload, edit)
5. **`gallery_photos`** — список фото у форматі JSON для повноекранної навігації
6. **`search_query`** — рядок пошуку з GET параметра
7. **`date_from`, `date_to`, `single_date`** — параметри фільтрації за датою
8. **`messages`** — Django messages framework для сповіщень

### Django Forms
У шаблонах edit.html та upload.html використовуються Django Form об'єкти:
- `{{ form.image }}` — рендерить поле завантаження файлу
- `{{ form.description }}` — текстове поле
- `{{ form.category }}` — випадаючий список (ModelChoiceField)
- `{{ form.category_new }}` — текстове поле для нової категорії
- `form.non_field_errors` — помилки не пов'язані з конкретним полем (наприклад, паролі не співпадають)
- `field.errors` — помилки валідації для конкретного поля
- `field.help_text` — підказка до поля
- `field.id_for_label` — ID поля для атрибута `for` у тегу `<label>`

### Pillow обробка зображень
Preview система в edit.html відправляє GET-запит на `/edit/<id>/preview/?brightness=30&contrast=10&...`

Django View для preview:
1. Отримує параметри з GET
2. Завантажує оригінальне зображення через Pillow `Image.open()`
3. Застосовує трансформації послідовно:
   - `ImageEnhance.Brightness` для яскравості
   - `ImageEnhance.Contrast` для контрасту
   - `ImageEnhance.Color` для насиченості
   - `ImageFilter.GaussianBlur` для розмиття
   - `Image.rotate()` для повороту
   - `Image.crop()` для обрізання (координати з `crop_x, crop_y, crop_w, crop_h`)
   - `ImageOps.mirror()` для дзеркального відображення
4. Зберігає результат у BytesIO
5. Повертає `HttpResponse` з `content_type='image/jpeg'`

При збереженні через POST — та ж логіка, але результат зберігається у файл через Django FileField.

### Моделі (з контексту шаблонів видно структуру):
- **Photo**: `image` (ImageField), `description` (CharField), `category` (ForeignKey), `created_at` (DateTimeField), `user` (ForeignKey до User)
- **Category**: `name` (CharField), `user` (ForeignKey)
- **User**: стандартна Django User модель

### GET параметри фільтрації
Gallery View отримує GET параметри:
- `?search=текст` → фільтрує photo.description через `icontains`
- `?category=назва` → фільтрує за назвою категорії
- `?date_from=2024-01-01` → фото після дати
- `?date_to=2024-12-31` → фото до дати
- `?single_date=2024-06-15` → за конкретну дату

Django View читає ці параметри через `request.GET.get('search', '')` і формує відповідний queryset.

---

## 2. JAVASCRIPT ЛОГІКА

### Система тем (Theme System)

**Desktop версія:**
- Використовує Bootstrap 5.3 data-attribute теми: `<html data-bs-theme="light">`
- JS змінює цей атрибут: `html.setAttribute('data-bs-theme', newTheme)`
- CSS перевизначає Bootstrap змінні через `[data-bs-theme="dark"]` селектори
- Використовує `!important` для перевизначення Bootstrap utility класів (наприклад, `.text-muted`)
- Зберігає вибір у `localStorage.setItem('theme', theme)`
- При завантаженні читає: `const savedTheme = localStorage.getItem('theme') || 'light'`
- IIFE (Immediately Invoked Function Expression) виконується одразу, до рендеру контенту

**Mobile версія:**
- Використовує CSS Custom Properties замість перевизначення Bootstrap
- `:root` містить змінні для світлої теми, `[data-bs-theme="dark"]` — для темної
- Всі кольори в CSS посилаються на `var(--bg-primary)`, `var(--text-primary)` тощо
- При зміні теми JS тільки міняє атрибут, CSS автоматично підхоплює нові значення змінних
- Додатково оновлює клас `btn-close-white` у Offcanvas компоненті Bootstrap

### Мовна система (i18n)
- Django стандартний механізм `django.middleware.locale.LocaleMiddleware`
- Форма з `<select onchange="this.form.submit()">` відправляє POST на `set_language/`
- Приховане поле `next` містить поточний URL для повернення
- Django обробляє POST, встановлює мову в сесії, редіректить на `next`
- Шаблони використовують `{% trans %}` для перекладу рядків

### Повноекранний переглядач (photo.html)

**Ініціалізація даних:**
- Django передає `gallery_photos` як JSON (список фото для навігації)
- Якщо `gallery_photos` немає в контексті, JavaScript створює масив з одного поточного фото
- `currentPhotoId` — ID поточного фото з контексту
- `currentIndex` — індекс поточного фото в масиві, знаходиться через `findIndex()`

**Логіка перегляду:**
- `openFullscreen()` шукає індекс поточного фото в масиві (на випадок зміни контексту)
- Викликає `updateFullscreenPhoto()` для встановлення зображення
- Додає клас `active` до модального вікна
- Блокує скрол сторінки: `document.body.style.overflow = 'hidden'`

**Навігація:**
- `goPrevPhoto()` / `goNextPhoto()` змінюють `currentIndex` ±1
- Викликають `updateFullscreenPhoto()` для оновлення
- Функція перевіряє межі масиву і встановлює `disabled` клас на стрілки
- Капшн формується з опису + категорії через роздільник "·"

**Закриття:**
- Кнопка закриття (X)
- Клік на фон (перевірка `e.target === modalElem`)
- Клавіша Escape
- `closeFullscreen()` прибирає клас `active` і відновлює скрол

### Система Crop (edit.html)

**Desktop версія (mouse-based):**
- `cropBox` — абсолютно позиціонований div з dashed border
- 8 handles: nw, n, ne, e, se, s, sw, w (кути + середини сторін)
- `crop-handle` — круглі точки 12px з зеленим border
- Затемнення через `box-shadow: 0 0 0 9999px rgba(0,0,0,0.5)` — величезна тінь навколо маленького боксу
- mousedown на handle → `isResizing = true`, запам'ятовує початкові координати
- mousemove → обчислює нові розміри в залежності від handle (наприклад, 'se' змінює width і height одночасно)
- mousedown на box → `isDragging = true` для переміщення
- Обмеження: не можна вийти за межі зображення, мінімальний розмір 20px
- `applyCrop()` конвертує піксельні координати в відсотки відносно розмірів зображення
- `getBoundingClientRect()` дає реальні розміри на екрані

**Mobile версія (touch-based):**
- Використовує Pointer Events API (уніфікована обробка миші та дотику)
- Тільки 4 handles (кути), розмір 22px — зручно для пальця
- `touch-action: none` на оверлеї запобігає браузерним жестам (зум, скрол)
- `setPointerCapture()` — захоплює вказівник для плавного перетягування
- `pointermove` обробляється на `window` для відстеження рухів за межами елемента
- Crop grid: rule-of-thirds лінії на 33.33% і 66.66%
- `startCrop(mode)` приймає режим: 'free', '1:1', '4:3', '16:9'
- Для режимів зі співвідношенням сторін обчислює розміри боксу з урахуванням пропорцій
- `updateCropCoords()` конвертує позицію боксу в відсотки, враховуючи зміщення зображення всередині контейнера
- `applyCrop()` використовує CSS `clip-path: inset()` для візуального обрізання

### Preview система

**Desktop (server-side):**
- `updatePreview()` викликається при зміні будь-якого слайдера
- Використовує debounce 150ms через `setTimeout`/`clearTimeout`
- Формує URLSearchParams з усіма параметрами (brightness, contrast, crop_x, etc.)
- Додає `_t=timestamp` для уникнення кешування браузером
- Встановлює `previewImg.src = url` — браузер завантажує нове зображення з сервера
- Сервер генерує зображення через Pillow і повертає JPEG

**Mobile (client-side):**
- `updatePreview()` застосовує CSS фільтри безпосередньо до `<img>` елемента
- Конвертує значення слайдерів у CSS filter рядок:
  - `brightness(${value})` — значення + 1 (бо 0 = нормальна яскравість)
  - `contrast(${value})`
  - `saturate(${value})`
  - `hue-rotate(${degrees}deg)`
  - `blur(${px}px)`
  - `drop-shadow()` для віньєтки
- Temperature впливає на hue-rotate: `hue + (temperature * 0.5)`
- Mirror реалізується через `transform: scaleX(-1)`
- Минає сервер, результат миттєвий, але обмежений можливостями CSS

### Система слайдерів (edit.html)

**Desktop:**
- 20+ `<input type="range">` з `oninput="updateValue('name')"`
- `updateValue()` оновлює відображення числа і викликає preview + історію
- `range-value` span можна клікнути — створюється `<input type="number">` для точного вводу
- Валідація через `dataset.min` і `dataset.max`
- Escape скидає значення, Enter підтверджує
- При виході з фокусу (blur) зберігає значення

**Mobile:**
- Один спільний слайдер `#activeSlider` для всіх параметрів
- Параметри вибираються через chips (пігулки) в горизонтальному скролі
- `selectParamChip()` оновлює min/max/value слайдера під вибраний параметр
- Вибраний chip отримує клас `selected` з акцентним кольором
- `chip.scrollIntoView()` прокручує до вибраного chip
- Поточні значення зберігаються в об'єкті `sliderValues`

### Історія редагувань (edit.html desktop)
- `editHistory` — масив об'єктів, кожен містить всі значення слайдерів + mirror
- `historyIndex` — поточний індекс в історії
- `saveToHistory()` — додає новий стан і обрізає "майбутнє" (якщо були undo)
- `loadFromHistory(index)` — відновлює всі слайдери зі збереженого стану
- `resetChanges()` — завантажує `historyIndex=0` (оригінальний стан)
- Історія оновлюється при кожній зміні слайдера або mirror

### Фільтри (edit.html)

**Desktop:**
- Модальне вікно з кнопками фільтрів
- Кожен фільтр скидає всі слайдери і встановлює специфічні значення
- Bright: brightness=30, contrast=10
- Warm: temperature=40, saturation=15
- Cool: temperature=-40, saturation=10
- Vivid: saturation=40, contrast=20
- Muted: saturation=-30, brightness=10
- Sepia: hue=30, saturation=20, brightness=5
- B&W: saturation=-100, contrast=15

**Mobile:**
- Чіпси внизу екрана замість модального вікна
- Та ж логіка значень, але застосовується до `sliderValues` об'єкта
- Оновлює слайдер якщо активна вкладка adjustments

### Save As логіка
- Відкриває модальне вікно з полем вводу назви файлу
- `saveAsField.value = '1'` — позначає що це save-as операція
- Назва файлу без розширення використовується як опис якщо він пустий
- При submit додає приховане поле `new_filename` до форми
- Сервер створює копію фото з новою назвою

### Camera Capture (upload_mobile.html)
- Кнопка "Take Photo" створює тимчасовий `<input type="file" capture="environment" accept="image/*">`
- `capture="environment"` — вказує браузеру використовувати задню камеру
- Після вибору файлу використовує DataTransfer API для копіювання:
  ```js
  const dataTransfer = new DataTransfer();
  dataTransfer.items.add(file);
  fileInput.files = dataTransfer.files;
