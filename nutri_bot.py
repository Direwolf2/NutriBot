import logging
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from openai import OpenAI, AuthenticationError, RateLimitError, APIError

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы для расчета
ACTIVITY_COEFFICIENTS = {
    'Минимальная': 1.2,
    'Низкая': 1.375,
    'Средняя': 1.55,
    'Высокая': 1.725,
    'Очень высокая': 1.9
}

GOAL_COEFFICIENTS = {
    'Похудеть': -0.2,
    'Поддерживать форму': 0,
    'Набрать массу': 0.2
}

# Инициализация диспетчера
dp = Dispatcher(storage=MemoryStorage())


# Определение состояний FSM
class UserStates(StatesGroup):
    gender = State()
    age = State()
    weight = State()
    height = State()
    activity = State()
    goal = State()
    menu = State()


def calculate_bmr(gender: str, weight: float, height: float, age: int) -> float:
    """Расчет базовой калорийности по формуле Миффлина-Сан-Жеора"""
    if gender == 'Мужской':
        return 10 * weight + 6.25 * height - 5 * age + 5
    else:  # Женский
        return 10 * weight + 6.25 * height - 5 * age - 161


def calculate_daily_calories(bmr: float, activity: str, goal: str) -> int:
    """Расчет суточной нормы калорий с учетом активности и цели"""
    activity_coef = ACTIVITY_COEFFICIENTS.get(activity, 1.2)
    goal_coef = GOAL_COEFFICIENTS.get(goal, 0)

    tdee = bmr * activity_coef  # Total Daily Energy Expenditure
    adjusted_calories = tdee * (1 + goal_coef)

    return round(adjusted_calories)


def calculate_macros(calories: int) -> dict:
    """Расчет БЖУ на основе калорийности"""
    # Стандартное соотношение БЖУ
    protein_calories = calories * 0.30  # 30% на белки
    fat_calories = calories * 0.25  # 25% на жиры
    carb_calories = calories * 0.45  # 45% на углеводы

    return {
        'protein': round(protein_calories / 4),  # 1г белка = 4 ккал
        'fat': round(fat_calories / 9),  # 1г жира = 9 ккал
        'carbs': round(carb_calories / 4)  # 1г углеводов = 4 ккал
    }


# Обработчик команды /start
@dp.message(Command('start'))
async def cmd_start(message: types.Message, state: FSMContext):
    """Приветствие и начало опроса"""
    welcome_message = (
        "👋 Привет! Добро пожаловать в нашего бота!\n\n"
        "Я помогу вам:\n"
        "✅ Рассчитать индивидуальную базовую калорийность по формуле Миффлина-Сан-Жеора\n"
        "✅ Сформировать текстовое меню на неделю с учетом БЖУ\n\n"
        "📋 Для начала мне нужно задать вам несколько вопросов.\n\n"
        "Укажите ваш пол:"
    )

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='Мужской'), KeyboardButton(text='Женский')]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await message.answer(welcome_message, reply_markup=keyboard)
    await state.set_state(UserStates.gender)


# Обработчик команды /cancel
@dp.message(Command('cancel'))
async def cmd_cancel(message: types.Message, state: FSMContext):
    """Отмена текущего действия"""
    await state.clear()
    await message.answer(
        "До свидания! Для начала новой анкеты используйте команду /start",
        reply_markup=ReplyKeyboardRemove()
    )


# Обработчик выбора пола
@dp.message(UserStates.gender)
async def process_gender(message: types.Message, state: FSMContext):
    """Сохранение пола и запрос возраста"""
    user_gender = message.text
    await state.update_data(gender=user_gender)

    await message.answer(
        f"Отлично! Вы выбрали: {user_gender}\n\n"
        "Теперь укажите ваш возраст (полных лет):",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(UserStates.age)


# Обработчик ввода возраста
@dp.message(UserStates.age)
async def process_age(message: types.Message, state: FSMContext):
    """Сохранение возраста и запрос веса"""
    try:
        user_age = int(message.text)
        if user_age < 10 or user_age > 120:
            await message.answer("Пожалуйста, укажите корректный возраст (от 10 до 120 лет):")
            return

        await state.update_data(age=user_age)

        await message.answer(
            f"Ваш возраст: {user_age} лет\n\n"
            "Укажите ваш вес (в килограммах):"
        )
        await state.set_state(UserStates.weight)
    except ValueError:
        await message.answer("Пожалуйста, введите число:")


# Обработчик ввода веса
@dp.message(UserStates.weight)
async def process_weight(message: types.Message, state: FSMContext):
    """Сохранение веса и запрос роста"""
    try:
        user_weight = float(message.text.replace(',', '.'))
        if user_weight < 30 or user_weight > 300:
            await message.answer("Пожалуйста, укажите корректный вес (от 30 до 300 кг):")
            return

        await state.update_data(weight=user_weight)

        await message.answer(
            f"Ваш вес: {user_weight} кг\n\n"
            "Укажите ваш рост (в сантиметрах):"
        )
        await state.set_state(UserStates.height)
    except ValueError:
        await message.answer("Пожалуйста, введите число:")


# Обработчик ввода роста
@dp.message(UserStates.height)
async def process_height(message: types.Message, state: FSMContext):
    """Сохранение роста и запрос уровня активности"""
    try:
        user_height = float(message.text.replace(',', '.'))
        if user_height < 100 or user_height > 250:
            await message.answer("Пожалуйста, укажите корректный рост (от 100 до 250 см):")
            return

        await state.update_data(height=user_height)

        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text='Минимальная')],
                [KeyboardButton(text='Низкая')],
                [KeyboardButton(text='Средняя')],
                [KeyboardButton(text='Высокая')],
                [KeyboardButton(text='Очень высокая')]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )

        await message.answer(
            f"Ваш рост: {user_height} см\n\n"
            "Выберите уровень физической активности:\n\n"
            "• Минимальная - сидячий образ жизни\n"
            "• Низкая - легкие упражнения 1-3 раза в неделю\n"
            "• Средняя - умеренные нагрузки 3-5 раз в неделю\n"
            "• Высокая - интенсивные тренировки 6-7 раз в неделю\n"
            "• Очень высокая - физическая работа или тренировки 2 раза в день",
            reply_markup=keyboard
        )
        await state.set_state(UserStates.activity)
    except ValueError:
        await message.answer("Пожалуйста, введите число:")


# Обработчик выбора активности
@dp.message(UserStates.activity)
async def process_activity(message: types.Message, state: FSMContext):
    """Сохранение уровня активности и запрос цели"""
    user_activity = message.text

    if user_activity not in ACTIVITY_COEFFICIENTS:
        await message.answer("Пожалуйста, выберите один из предложенных вариантов:")
        return

    await state.update_data(activity=user_activity)

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='Похудеть')],
            [KeyboardButton(text='Поддерживать форму')],
            [KeyboardButton(text='Набрать массу')]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await message.answer(
        f"Уровень активности: {user_activity}\n\n"
        "Какая у вас цель?",
        reply_markup=keyboard
    )
    await state.set_state(UserStates.goal)


# Обработчик выбора цели
@dp.message(UserStates.goal)
async def process_goal(message: types.Message, state: FSMContext):
    """Сохранение цели и вывод результатов расчета"""
    user_goal = message.text

    if user_goal not in GOAL_COEFFICIENTS:
        await message.answer("Пожалуйста, выберите один из предложенных вариантов:")
        return

    await state.update_data(goal=user_goal)

    # Получаем все данные из состояния
    data = await state.get_data()

    # Расчет калорийности
    bmr = calculate_bmr(
        data['gender'],
        data['weight'],
        data['height'],
        data['age']
    )

    daily_calories = calculate_daily_calories(
        bmr,
        data['activity'],
        data['goal']
    )

    macros = calculate_macros(daily_calories)

    # Сохраняем расчетные данные
    await state.update_data(
        bmr=bmr,
        daily_calories=daily_calories,
        macros=macros
    )

    result_message = (
        "✅ Анкета заполнена! Спасибо!\n\n"
        "📊 Ваши данные:\n"
        f"• Пол: {data['gender']}\n"
        f"• Возраст: {data['age']} лет\n"
        f"• Вес: {data['weight']} кг\n"
        f"• Рост: {data['height']} см\n"
        f"• Активность: {data['activity']}\n"
        f"• Цель: {data['goal']}\n\n"
        f"🔥 Базовый обмен веществ (BMR): {round(bmr)} ккал\n"
        f"🎯 Суточная норма калорий: {daily_calories} ккал\n\n"
        f"📈 Норма БЖУ:\n"
        f"• Белки: {macros['protein']} г\n"
        f"• Жиры: {macros['fat']} г\n"
        f"• Углеводы: {macros['carbs']} г\n\n"
        "Выберите действие:"
    )

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='📋 Мои данные'), KeyboardButton(text='🔄 Пересчитать')],
            [KeyboardButton(text='🍽 Сгенерировать меню'), KeyboardButton(text='🆕 Новое меню')]
        ],
        resize_keyboard=True
    )

    await message.answer(result_message, reply_markup=keyboard)
    await state.set_state(UserStates.menu)


# Обработчик меню "Мои данные"
@dp.message(UserStates.menu, F.text == '📋 Мои данные')
async def show_my_data(message: types.Message, state: FSMContext):
    """Показать сохраненные данные пользователя"""
    data = await state.get_data()

    message_text = (
        "📊 Ваши данные:\n\n"
        f"• Пол: {data.get('gender', 'Не указан')}\n"
        f"• Возраст: {data.get('age', 'Не указан')} лет\n"
        f"• Вес: {data.get('weight', 'Не указан')} кг\n"
        f"• Рост: {data.get('height', 'Не указан')} см\n"
        f"• Активность: {data.get('activity', 'Не указана')}\n"
        f"• Цель: {data.get('goal', 'Не указана')}\n\n"
        f"🔥 Базовый обмен: {round(data.get('bmr', 0))} ккал\n"
        f"🎯 Суточная норма: {data.get('daily_calories', 0)} ккал\n\n"
        f"📈 Норма БЖУ:\n"
        f"• Белки: {data.get('macros', {}).get('protein', 0)} г\n"
        f"• Жиры: {data.get('macros', {}).get('fat', 0)} г\n"
        f"• Углеводы: {data.get('macros', {}).get('carbs', 0)} г"
    )

    await message.answer(message_text)


# Обработчик меню "Пересчитать"
@dp.message(UserStates.menu, F.text == '🔄 Пересчитать')
async def recalculate(message: types.Message, state: FSMContext):
    """Начать заполнение анкеты заново"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='Мужской'), KeyboardButton(text='Женский')]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await message.answer(
        "Начинаем заново! Укажите ваш пол:",
        reply_markup=keyboard
    )
    await state.set_state(UserStates.gender)


# Обработчик генерации меню
@dp.message(UserStates.menu, F.text.in_(['🍽 Сгенерировать меню', '🆕 Новое меню']))
async def generate_menu(message: types.Message, state: FSMContext, openai_client: OpenAI):
    """Генерация персонализированного меню через OpenAI"""
    data = await state.get_data()

    await message.answer("🤖 Генерирую персонализированное меню... Это может занять несколько секунд.")

    try:
        # Формирование промпта для ИИ
        prompt = (
            f"Создай подробное сбалансированное меню на неделю для пользователя со следующими параметрами:\n\n"
            f"Пол: {data.get('gender')}\n"
            f"Возраст: {data.get('age')} лет\n"
            f"Вес: {data.get('weight')} кг\n"
            f"Рост: {data.get('height')} см\n"
            f"Уровень активности: {data.get('activity')}\n"
            f"Цель: {data.get('goal')}\n\n"
            f"Суточная норма калорий: {data.get('daily_calories')} ккал\n"
            f"Норма белков: {data.get('macros', {}).get('protein')} г/день\n"
            f"Норма жиров: {data.get('macros', {}).get('fat')} г/день\n"
            f"Норма углеводов: {data.get('macros', {}).get('carbs')} г/день\n\n"
            f"Требования:\n"
            f"1. Создай меню на 7 дней с завтраком, обедом, ужином и 2 перекусами\n"
            f"2. Для каждого блюда укажи примерную калорийность и БЖУ\n"
            f"3. Меню должно быть разнообразным и вкусным\n"
            f"4. Учитывай цель пользователя: {data.get('goal')}\n"
            f"5. Формат: День X -> приемы пищи с названиями блюд и калорийностью"
        )

        # Запрос к OpenAI API
        response = openai_client.chat.completions.create(
            model="gpt-4o",  # или "gpt-3.5-turbo" для более быстрых и дешевых ответов
            messages=[
                {
                    "role": "system",
                    "content": """Ты профессиональный нутрициолог и диетолог, специализирующийся на составлении планов питания для жителей России.

                ВАЖНЫЕ ТРЕБОВАНИЯ К МЕНЮ:

                1. ТОЛЬКО доступные в России продукты:
                   - Мясо: курица, говядина, свинина, индейка
                   - Рыба: скумбрия, сазан, минтай, горбуша, сom
                   - Крупы: гречка, рис
                   - Гарниры: макароны, картофель (вареный/печеный), гречка, рис
                   - Овощи: капуста, морковь, свекла, огурцы, помидоры, лук
                   - Фрукты: яблоки, бананы, апельсины, груши
                   - Молочное: творог, кефир, молоко, сметана, йогурт натуральный
                   - Яйца куриные

                2. ИСКЛЮЧИТЬ экзотические продукты:
                   - НЕ использовать: киноа, семена чиа, авокадо, кускус, булгур, шпинат, руккола, кейл
                   - НЕ использовать дорогие/редкие ингредиенты

                3. Простые блюда:
                   - Привычная российская кухня
                   - Простые способы приготовления (варка, запекание, тушение)
                   - Реалистичные рецепты, которые легко готовить дома

                4. Примеры блюд:
                   - Завтрак: овсянка, яичница, творог с фруктами, омлет
                   - Обед: куриная грудка с гречкой, рыба с рисом, говядина с макаронами
                   - Ужин: запеченная рыба с овощами, куриные котлеты с картофелем
                   - Перекусы: яблоко, творог, кефир, горсть орехов, банан

                5. Учитывай сезонность и доступность продуктов в обычных российских магазинах.

                Создавай разнообразное, но ПРОСТОЕ и ДОСТУПНОЕ меню с точным расчетом БЖУ и калорийности."""
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.7,
            max_tokens=3000
        )

        # Получение ответа от ИИ
        menu_text = response.choices[0].message.content

        # Отправка меню пользователю (разбиваем на части, если слишком длинное)
        if len(menu_text) > 4096:  # Ограничение Telegram на длину сообщения
            # Разбиваем текст на части по 4000 символов
            parts = [menu_text[i:i + 4000] for i in range(0, len(menu_text), 4000)]
            for i, part in enumerate(parts, 1):
                await message.answer(f"📋 Ваше меню (часть {i}/{len(parts)}):\n\n{part}")
        else:
            await message.answer(f"📋 Ваше персонализированное меню на неделю:\n\n{menu_text}")

    except AuthenticationError:
        await message.answer(
            "❌ Ошибка аутентификации OpenAI API.\n"
            "Проверьте правильность токена OPENAI_API_KEY в коде."
        )
    except RateLimitError:
        await message.answer(
            "⚠️ Превышен лимит запросов к OpenAI API.\n"
            "Пожалуйста, попробуйте позже."
        )
    except APIError as e:
        await message.answer(
            f"❌ Ошибка API OpenAI: {str(e)}\n"
            "Пожалуйста, попробуйте позже."
        )
    except Exception as e:
        logger.error(f"Ошибка при генерации меню: {e}")
        await message.answer(
            "❌ Произошла ошибка при генерации меню.\n"
            "Пожалуйста, попробуйте еще раз."
        )


async def main():
    """Главная функция запуска бота"""
    # ВАЖНО: Замените на ваши реальные токены
    TELEGRAM_TOKEN = '8249391522:AAGelANhcHQ95XZzmU8ed_wUjomz-3I9Liw'
    OPENAI_API_KEY = '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'

    # Создание клиента OpenAI
    openai_client = OpenAI(api_key=OPENAI_API_KEY)

    # Инициализация бота
    bot = Bot(token=TELEGRAM_TOKEN)

    # Сохраняем клиент OpenAI в workflow_data для доступа из обработчиков
    dp.workflow_data.update(openai_client=openai_client)

    # Запуск бота
    logger.info("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())