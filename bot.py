import os
import logging
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ========== НАСТРОЙКА ЛОГГИРОВАНИЯ ==========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)

# ========== КОНФИГУРАЦИЯ ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_telegram_bot_token")
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@your_channel")

# ========== СОСТОЯНИЯ ИГРЫ ==========
class GameState:
    def __init__(self):
        # Основные метрики (0-10)
        self.career = 0
        self.family = 0 
        self.energy = 8
        self.skills = 0
        
        # Время и прогресс
        self.hours = 15
        self.minutes = 0
        self.day = 1
        self.total_score = 0
        self.days_completed = 0
        self.day_type = "normal"
        
        # Игровые механики
        self.achievements = []
        self.special_events_seen = []
        
        # Системные
        self.checked_subscription = False
        self.current_scene = "start"
        self.player_name = "Герой"
        self.pending_scene = None

# ========== ГЛОБАЛЬНОЕ ХРАНИЛИЩЕ ==========
user_states = {}

# ========== СИСТЕМА ВРЕМЕНИ ==========
def add_time(state, hours=0, minutes=0):
    """Добавляет время и возвращает обновленное состояние"""
    total_minutes = state.hours * 60 + state.minutes + hours * 60 + minutes
    state.hours = total_minutes // 60
    state.minutes = total_minutes % 60
    return state

def time_to_str(state):
    return f"{state.hours:02d}:{state.minutes:02d}"

def is_late(state):
    return state.hours > 18 or (state.hours == 18 and state.minutes > 40)

# ========== ПРОВЕРКА ПОДПИСКИ ==========
async def check_subscription(user_id, context: ContextTypes.DEFAULT_TYPE):
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logging.error(f"Ошибка проверки подписки: {e}")
        return False

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
async def remove_buttons_and_show_choice(query, choice_text):
    try:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"👤 {choice_text}")
    except Exception as e:
        logging.error(f"Ошибка при удалении кнопок: {e}")

async def restart_game(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    user_states[user_id] = GameState()
    await start(update, context)

def calculate_total_score(state):
    base_score = (state.career + state.family + state.energy + state.skills) * 10
    day_bonus = state.days_completed * 50
    achievement_bonus = len(state.achievements) * 30
    
    total = base_score + day_bonus + achievement_bonus
    
    # Бонусы за высокие показатели
    if state.career >= 8: total += 50
    if state.family >= 8: total += 50  
    if state.energy >= 8: total += 50
    if state.skills >= 8: total += 50
        
    return total

def generate_day_type(state):
    day_types = ["normal", "career_crisis", "family_crisis", "lucky_day", "energy_drain", "skill_focus"]
    
    if state.days_completed >= 3 and random.random() < 0.6:
        return random.choice(["career_crisis", "family_crisis", "energy_drain"])
    
    return random.choice(day_types)

def get_day_modifiers(day_type):
    modifiers = {
        "normal": {"time_mod": 1.0, "energy_mod": 1.0},
        "career_crisis": {"time_mod": 1.2, "energy_mod": 0.8, "career_bonus": 1},
        "family_crisis": {"time_mod": 1.3, "energy_mod": 0.7, "family_bonus": 1},
        "lucky_day": {"time_mod": 0.8, "energy_mod": 1.2},
        "energy_drain": {"time_mod": 1.1, "energy_mod": 0.6},
        "skill_focus": {"time_mod": 1.0, "energy_mod": 1.1, "skill_bonus": 1}
    }
    return modifiers.get(day_type, modifiers["normal"])

async def share_results_button(query, state):
    share_text = f"Я·играю·в·Гонку·до·Универа!·День:{state.day}|Счет:{state.total_score}|Энергия:{state.energy}|Карьера:{state.career}|Семья:{state.family}|Навыки:{state.skills}|Достижений:{len(state.achievements)}|Присоединяйся!"
    
    share_url = f"https://t.me/share/url?url=https://t.me/SurvivalStudentGameBot&text={share_text}"
    
    keyboard = [
        [InlineKeyboardButton("📤 Поделиться результатом", url=share_url)],
        [InlineKeyboardButton("🔄 Следующий день", callback_data="next_day")],
        [InlineKeyboardButton("🔄 Начать заново", callback_data="restart")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ========== СЛУЧАЙНЫЕ СОБЫТИЯ ==========
async def trigger_random_event(query, state, force_chance=None):
    chance = force_chance if force_chance is not None else 0.4
    
    if state.day_type == "lucky_day":
        chance = 0.7
    
    if random.random() > chance:
        return state, False
    
    events = [
        {
            "id": "bonus_award",
            "text": "🎁 СРОЧНАЯ ПРЕМИЯ!\n\nТвой проект получил срочное финансирование! Начальник даёт отгул!",
            "effects": {"minutes": -90, "career": 2, "energy": 1},
            "achievement": "Золотой сотрудник"
        },
        {
            "id": "friend_help", 
            "text": "🤝 ПОМОЩЬ НА ДОРОГЕ!\n\nДруг встретил по пути и подвёз до универа!",
            "effects": {"minutes": -40, "family": 1},
            "achievement": "Настоящий друг"
        },
        {
            "id": "traffic_jam",
            "text": "🚗 ПРОБКА НА ДОРОГЕ!\n\nНеожиданная пробка задержала на полчаса!",
            "effects": {"minutes": 30, "energy": -1},
            "achievement": None
        },
        {
            "id": "kids_amazing",
            "text": "🏆 ДЕТИ ПОМОГАЮТ!\n\nДети сами сделали уроки и освободили время!",
            "effects": {"minutes": -45, "family": 2, "energy": 1},
            "achievement": "Суперродитель"
        }
    ]
    
    available_events = [e for e in events if e["id"] not in state.special_events_seen]
    if not available_events:
        available_events = events
    
    event = random.choice(available_events)
    state.special_events_seen.append(event["id"])
    
    old_time = f"{state.hours:02d}:{state.minutes:02d}"
    
    # ПРИМЕНЯЕМ ЭФФЕКТЫ
    if "minutes" in event["effects"]:
        state = add_time(state, minutes=event["effects"]["minutes"])
    if "career" in event["effects"]:
        state.career = min(10, max(0, state.career + event["effects"]["career"]))
    if "family" in event["effects"]:
        state.family = min(10, max(0, state.family + event["effects"]["family"]))
    if "energy" in event["effects"]:
        state.energy = min(10, max(0, state.energy + event["effects"]["energy"]))
    if "skills" in event["effects"]:
        state.skills = min(10, max(0, state.skills + event["effects"]["skills"]))
    
    new_time = f"{state.hours:02d}:{state.minutes:02d}"
    
    text = f"🎲 СЛУЧАЙНОЕ СОБЫТИЕ!\n\n{event['text']}"
    
    # Показываем эффекты
    effects_text = ""
    if "minutes" in event["effects"]:
        effects_text += f"⏰ Время: {old_time} → {new_time}\n"
    if "career" in event["effects"] and event["effects"]["career"] != 0:
        effects_text += f"💼 Карьера {event['effects']['career']:+d}\n"
    if "family" in event["effects"] and event["effects"]["family"] != 0:
        effects_text += f"👨‍👩‍👧‍👦 Семья {event['effects']['family']:+d}\n"
    if "energy" in event["effects"] and event["effects"]["energy"] != 0:
        effects_text += f"⚡ Энергия {event['effects']['energy']:+d}\n"
    
    if effects_text:
        text += f"\nЭффекты:\n{effects_text}"
    
    if event["achievement"] and event["achievement"] not in state.achievements:
        state.achievements.append(event["achievement"])
        text += f"\n🏆 Получено достижение: {event['achievement']}"
    
    keyboard = [[InlineKeyboardButton("✨ Продолжить", callback_data="continue_after_event")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.reply_text(text, reply_markup=reply_markup)
    return state, True

# ========== ОСНОВНЫЕ СЦЕНЫ ИГРЫ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        user_id = update.message.from_user.id
        message = update.message
    else:
        query = update.callback_query
        user_id = query.from_user.id
        message = query.message
    
    user_states[user_id] = GameState()
    state = user_states[user_id]
    
    first_name = update.effective_user.first_name or "Герой"
    state.player_name = first_name
    
    welcome_text = (
        f"🎮 ГОНКА ДО УНИВЕРА: ИСКУССТВО ЖИЗНЕННОГО БАЛАНСА\n\n"
        f"Привет, {first_name}! 👋\n\n"
        "Ты — современный супергерой: студент вечернего отделения, работник, партнер и родитель троих детей!\n\n"
        "ТВОЯ МИССИЯ:\n"
        "🕒 Успеть на пару к 18:40\n"  
        "👨‍👩‍👧‍👦 Сохранить семью счастливой\n"
        "💼 Не потерять работу\n"
        "⚡ Не выгореть от усталости\n\n"
        "ОСОБЕННОСТИ:\n"
        "👉 Случайные события и кризисы\n"
        "👉 Система прокачки навыков\n"
        "👉 Достижения и рейтинг\n"
        "👉 Многодневная кампания\n\n"
        f"📢 Для старта подпишись на канал автора:\n{CHANNEL_USERNAME}"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔍 Проверить подписку", callback_data="check_subscription")],
        [InlineKeyboardButton("📺 Перейти в канал", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await message.reply_text(welcome_text, reply_markup=reply_markup)

async def start_day_message(query, state):
    state.day_type = generate_day_type(state)
    
    day_descriptions = {
        "normal": "📅 ОБЫЧНЫЙ ДЕНЬ\nСтандартные вызовы и задачи",
        "career_crisis": "💥 КРИЗИС НА РАБОТЕ\nЗадачи сложнее, но больше карьерного опыта",  
        "family_crisis": "👨‍👩‍👧‍👦 СЕМЕЙНЫЙ КРИЗИС\nСемья требует больше внимания и заботы",
        "lucky_day": "🍀 УДАЧНЫЙ ДЕНЬ\nВыше шанс позитивных событий и бонусов",
        "energy_drain": "😫 ДЕНЬ УСТАЛОСТИ\nЭнергия тратится быстрее, нужна осторожность",
        "skill_focus": "🔧 ДЕНЬ НАВЫКОВ\nОтличная возможность прокачать умения"
    }
    
    day_text = (
        f"🎮 ГОНКА ДО УНИВЕРА: День {state.day} 🎮\n\n"
        f"🌟 {day_descriptions[state.day_type]}\n\n"
        f"🕒 Сейчас {time_to_str(state)}\n"
        f"📚 Пары начинаются в 18:40\n\n"
        f"⚡ Твои ресурсы:\n"
        f"Энергия: {state.energy}/10\n"
        f"Карьера: {state.career}/10\n"
        f"Семья: {state.family}/10\n"
        f"Навыки: {state.skills}/10\n\n"
        "Готов к новым вызовам?"
    )
    
    keyboard = [[InlineKeyboardButton("🚀 Начать день!", callback_data="start_day")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.reply_text(day_text, reply_markup=reply_markup)

# ========== ИСПРАВЛЕННЫЙ ОБРАБОТЧИК CALLBACK ==========
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    current_state = user_states.get(user_id)
    
    if not current_state:
        await query.edit_message_text("Игра не найдена. Начни заново: /start")
        return

    # ========== СИСТЕМНЫЕ КОМАНДЫ ==========
    if query.data == "restart":
        await remove_buttons_and_show_choice(query, "Начать заново 🔄")
        await restart_game(update, context, user_id)
        return

    elif query.data == "check_subscription":
        if await check_subscription(user_id, context):
            current_state.checked_subscription = True
            await remove_buttons_and_show_choice(query, "Подписка проверена ✅")
            await start_day_message(query, current_state)
        else:
            text = (
                "❌ Вы еще не подписаны на канал\n\n"
                "Подпишитесь на канал и нажмите кнопку проверки:\n"
                f"{CHANNEL_USERNAME}"
            )
            keyboard = [
                [InlineKeyboardButton("🔍 Проверить подписку", callback_data="check_subscription")],
                [InlineKeyboardButton("📺 Перейти в канал", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(text, reply_markup=reply_markup)
        return

    elif query.data == "start_day":
        await remove_buttons_and_show_choice(query, "Начинаем день! 🚀")
        await scene_work_start(query, current_state)
        return

    elif query.data == "continue_after_event":
        if current_state.pending_scene == "work_decision":
            await scene_work_decision(query, current_state)
        elif current_state.pending_scene == "family":
            await scene_family_crisis(query, current_state)
        elif current_state.pending_scene == "partner":
            await scene_partner_dilemma(query, current_state)
        elif current_state.pending_scene == "transport":
            await scene_transport(query, current_state)
        elif current_state.pending_scene == "final":
            await final_scene(query, current_state)
        else:
            await scene_work_start(query, current_state)
        return

    # Проверка подписки для игровых действий
    if not current_state.checked_subscription:
        text = "⛔ Сначала подпишись на канал"
        keyboard = [[InlineKeyboardButton("🔍 Проверить подписку", callback_data="check_subscription")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup)
        return

    # ========== ОСНОВНАЯ ИГРОВАЯ ЛОГИКА ==========
    
    # РАБОТА - ИСПРАВЛЕННЫЕ БАЛЛЫ И ВРЕМЯ
    if query.data == "work_quality":
        await remove_buttons_and_show_choice(query, "Сделать качественный отчёт 📊")
        modifiers = get_day_modifiers(current_state.day_type)
        time_cost = 120  # Фиксированное время, без модификаторов для ясности
        current_state = add_time(current_state, minutes=time_cost)
        career_bonus = 3
        current_state.career = min(10, current_state.career + career_bonus)
        energy_cost = 2
        current_state.energy = max(0, current_state.energy - energy_cost)
        current_state.skills += 1
        current_state.pending_scene = "work_decision"
        current_state, event_happened = await trigger_random_event(query, current_state, force_chance=0.3)
        if not event_happened:
            await scene_work_decision(query, current_state)
    
    elif query.data == "work_fast":
        await remove_buttons_and_show_choice(query, "Сделать быстрый отчёт ⚡")
        time_cost = 60
        current_state = add_time(current_state, minutes=time_cost)
        career_bonus = 1
        current_state.career = min(10, current_state.career + career_bonus)
        energy_cost = 1
        current_state.energy = max(0, current_state.energy - energy_cost)
        current_state.pending_scene = "work_decision"
        current_state, event_happened = await trigger_random_event(query, current_state, force_chance=0.3)
        if not event_happened:
            await scene_work_decision(query, current_state)
    
    elif query.data == "work_skip":
        await remove_buttons_and_show_choice(query, "Передать коллеге 🚶")
        time_cost = 30
        current_state = add_time(current_state, minutes=time_cost)
        current_state.career = max(0, current_state.career - 1)
        energy_cost = 1
        current_state.energy = max(0, current_state.energy - energy_cost)
        current_state.pending_scene = "family"
        current_state, event_happened = await trigger_random_event(query, current_state, force_chance=0.3)
        if not event_happened:
            await scene_family_crisis(query, current_state)
    
    # СЕМЬЯ - ИСПРАВЛЕННЫЕ БАЛЛЫ И ВРЕМЯ
    elif query.data == "family_help":
        await remove_buttons_and_show_choice(query, "Помочь всем детям 👨‍👩‍👧‍👦")
        time_cost = 90
        current_state = add_time(current_state, minutes=time_cost)
        family_bonus = 3
        current_state.family = min(10, current_state.family + family_bonus)
        energy_cost = 2
        current_state.energy = max(0, current_state.energy - energy_cost)
        current_state.skills += 1
        current_state.pending_scene = "partner"
        current_state, event_happened = await trigger_random_event(query, current_state, force_chance=0.3)
        if not event_happened:
            await scene_partner_dilemma(query, current_state)
    
    elif query.data == "family_quick":
        await remove_buttons_and_show_choice(query, "Быстрая помощь ⏱️")
        time_cost = 45
        current_state = add_time(current_state, minutes=time_cost)
        family_bonus = 1
        current_state.family = min(10, current_state.family + family_bonus)
        energy_cost = 1
        current_state.energy = max(0, current_state.energy - energy_cost)
        current_state.pending_scene = "partner"
        current_state, event_happened = await trigger_random_event(query, current_state, force_chance=0.3)
        if not event_happened:
            await scene_partner_dilemma(query, current_state)
    
    elif query.data == "family_money":
        await remove_buttons_and_show_choice(query, "Нанять помощника 💰")
        time_cost = 20
        current_state = add_time(current_state, minutes=time_cost)
        family_bonus = 2
        current_state.family = min(10, current_state.family + family_bonus)
        current_state.pending_scene = "partner"
        current_state, event_happened = await trigger_random_event(query, current_state, force_chance=0.3)
        if not event_happened:
            await scene_partner_dilemma(query, current_state)
    
    # ПАРТНЕР - ИСПРАВЛЕННЫЕ БАЛЛЫ И ВРЕМЯ
    elif query.data == "partner_help":
        await remove_buttons_and_show_choice(query, "Помочь с родителями 🎁")
        time_cost = 90
        current_state = add_time(current_state, minutes=time_cost)
        family_bonus = 2
        current_state.family = min(10, current_state.family + family_bonus)
        energy_cost = 1
        current_state.energy = max(0, current_state.energy - energy_cost)
        current_state.skills += 1
        current_state.pending_scene = "transport"
        current_state, event_happened = await trigger_random_event(query, current_state, force_chance=0.3)
        if not event_happened:
            await scene_transport(query, current_state)
    
    elif query.data == "partner_apologize":
        await remove_buttons_and_show_choice(query, "Извиниться и пообещать 💐")
        time_cost = 30
        current_state = add_time(current_state, minutes=time_cost)
        family_bonus = 1
        current_state.family = min(10, current_state.family + family_bonus)
        current_state.pending_scene = "transport"
        current_state, event_happened = await trigger_random_event(query, current_state, force_chance=0.3)
        if not event_happened:
            await scene_transport(query, current_state)
    
    elif query.data == "partner_ignore":
        await remove_buttons_and_show_choice(query, "Перенести на завтра ❌")
        time_cost = 10
        current_state = add_time(current_state, minutes=time_cost)
        current_state.family = max(0, current_state.family - 2)
        energy_cost = 1
        current_state.energy = max(0, current_state.energy - energy_cost)
        current_state.pending_scene = "transport"
        current_state, event_happened = await trigger_random_event(query, current_state, force_chance=0.3)
        if not event_happened:
            await scene_transport(query, current_state)
    
    # ТРАНСПОРТ - ФИКСИРОВАННОЕ ВРЕМЯ
    elif query.data == "transport_fix":
        await remove_buttons_and_show_choice(query, "Починить машину 🔧")
        time_cost = 60
        current_state = add_time(current_state, minutes=time_cost)
        current_state.skills += 2
        current_state.pending_scene = "final"
        current_state, event_happened = await trigger_random_event(query, current_state, force_chance=0.3)
        if not event_happened:
            await final_scene(query, current_state)
    
    elif query.data == "transport_taxi":
        await remove_buttons_and_show_choice(query, "Вызвать такси 🚕")
        time_cost = 25
        current_state = add_time(current_state, minutes=time_cost)
        current_state.skills += 1
        current_state.pending_scene = "final"
        current_state, event_happened = await trigger_random_event(query, current_state, force_chance=0.3)
        if not event_happened:
            await final_scene(query, current_state)
    
    elif query.data == "transport_bus":
        await remove_buttons_and_show_choice(query, "Ехать на автобусе 🚌")
        time_cost = 50
        current_state = add_time(current_state, minutes=time_cost)
        current_state.pending_scene = "final"
        current_state, event_happened = await trigger_random_event(query, current_state, force_chance=0.3)
        if not event_happened:
            await final_scene(query, current_state)
    
    # СЛУШАЕМ ПРОБЛЕМУ СЕМЬИ
    elif query.data == "listen_family":
        await remove_buttons_and_show_choice(query, "Выслушал проблему семьи 👂")
        await scene_family_crisis(query, current_state)
        return
    
    # СИСТЕМНЫЕ КОМАНДЫ
    elif query.data == "show_stats":
        await show_statistics(query, current_state)
    elif query.data == "show_achievements":
        await show_achievements(query, current_state)
    elif query.data == "next_day":
        await start_new_day(query, current_state)
    elif query.data == "share_progress":
        reply_markup = await share_results_button(query, current_state)
        await query.message.reply_text(
            "🎮 Поделись своим успехом!\n\nПусть друзья узнают, как ты круто балансируешь жизнь!", 
            reply_markup=reply_markup
        )

# ========== ИГРОВЫЕ СЦЕНЫ ==========
async def scene_work_start(query, state):
    state.current_scene = "work"
    
    work_messages = [
        f"💼 РАБОТА\n\n{state.player_name}, начальник ставит задачу:\n«Нужен детальный отчёт по кварталу. Без этого не получим финансирование!»",
        f"💼 РАБОТА\n\n{state.player_name}, срочное задание:\n«Клиент ждёт отчёт до конца дня. От этого зависит наш крупный контракт.»"
    ]
    
    text = (
        f"🕒 День {state.day} | {time_to_str(state)}\n\n"
        f"{random.choice(work_messages)}\n\n"
        "Твои действия?"
    )
    
    keyboard = [
        [InlineKeyboardButton("📊 Качественный отчёт (2 часа)", callback_data="work_quality")],
        [InlineKeyboardButton("⚡ Быстрый отчёт (1 час)", callback_data="work_fast")],
        [InlineKeyboardButton("🚶 Передать коллеге (30 минут)", callback_data="work_skip")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(text, reply_markup=reply_markup)

async def scene_work_decision(query, state):
    text = (
        f"🕒 {time_to_str(state)}\n\n"
        "📈 ИТОГИ РАБОТЫ\n\n"
        "Отчёт сдан! Время двигаться дальше.\n\n"
        "Звонит партнёр, голос дрожит:\n«Нужна помощь дома! Срочно!»\n\nСлушаешь?"
    )
    
    keyboard = [[InlineKeyboardButton("✅ Выслушать проблему", callback_data="listen_family")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(text, reply_markup=reply_markup)

async def scene_family_crisis(query, state):
    state.current_scene = "family"
    
    family_situations = [
        f"👨‍👩‍👧‍👦 СЕМЕЙНЫЙ КРИЗИС\n\n{state.player_name}, партнёр в панике:\n«Старший не сдал проект, средний заболел, младший устроил потоп в ванной!»",
        f"🏠 ДОМАШНИЙ ХАОС\n\n{state.player_name}, дома настоящий шторм:\n«У детей срочные школьные проекты, нужно готовить ужин, а младший плачет!»"
    ]
    
    text = (
        f"🕒 {time_to_str(state)}\n\n"
        f"{random.choice(family_situations)}\n\n"
        "Как спасать ситуацию?"
    )
    
    keyboard = [
        [InlineKeyboardButton("👨‍👩‍👧‍👦 Помочь всем (1 час 30 минут)", callback_data="family_help")],
        [InlineKeyboardButton("⏱️ Быстрая помощь (45 минут)", callback_data="family_quick")],
        [InlineKeyboardButton("💰 Нанять помощника (20 минут)", callback_data="family_money")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(text, reply_markup=reply_markup)

async def scene_partner_dilemma(query, state):
    partner_messages = [
        f"❤️ ОТНОШЕНИЯ\n\nПартнёр смотрит с надеждой:\n«Сегодня юбилей у мамы. Она ждёт, что мы заедем. Знаю, ты устал, но это важно для меня...»",
        f"🏡 СЕМЕЙНЫЕ ЦЕННОСТИ\n\nВторая половинка говорит:\n«Родители ждут нас на ужин. Можешь выкроить время? Это многое для меня значит.»"
    ]
    
    text = (
        f"🕒 {time_to_str(state)}\n\n"
        f"{random.choice(partner_messages)}\n\n"
        "Твой ответ?"
    )
    
    keyboard = [
        [InlineKeyboardButton("🎁 Поехать к родителям (1 час 30 минут)", callback_data="partner_help")],
        [InlineKeyboardButton("💐 Извиниться и пообещать (30 минут)", callback_data="partner_apologize")],
        [InlineKeyboardButton("❌ Перенести на завтра (10 минут)", callback_data="partner_ignore")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(text, reply_markup=reply_markup)

async def scene_transport(query, state):
    state.current_scene = "transport"
    text = (
        f"🕒 {time_to_str(state)}\n\n"
        "🚗 ФИНАЛЬНЫЙ РЫВОК\n\n"
        "Выбегаешь из дома. Машина не заводится — сел аккумулятор!\n\n"
        "До пары остаётся всё меньше времени...\n\n"
        "Выбирай транспорт:"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔧 Починить машину (1 час)", callback_data="transport_fix")],
        [InlineKeyboardButton("🚕 Вызвать такси (25 минут)", callback_data="transport_taxi")],
        [InlineKeyboardButton("🚌 Автобус (50 минут)", callback_data="transport_bus")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(text, reply_markup=reply_markup)

# ========== СИСТЕМНЫЕ ФУНКЦИИ ==========
async def show_statistics(query, state):
    state.total_score = calculate_total_score(state)
    
    text = (
        f"📊 ДЕТАЛЬНАЯ СТАТИСТИКА ДНЯ {state.day}\n\n"
        f"💼 Карьера: {state.career}/10 - {'Отлично' if state.career >= 7 else 'Хорошо' if state.career >= 4 else 'Проблемы'}\n"
        f"👨‍👩‍👧‍👦 Семья: {state.family}/10 - {'Счастлива' if state.family >= 7 else 'Довольна' if state.family >= 4 else 'Обижена'}\n"
        f"⚡ Энергия: {state.energy}/10 - {'Полон сил' if state.energy >= 7 else 'Нормально' if state.energy >= 4 else 'Устал'}\n"
        f"🔧 Навыки: {state.skills}/10 - {'Мастер' if state.skills >= 7 else 'Развивается' if state.skills >= 4 else 'Новичок'}\n\n"
        
        f"⭐ ОБЩИЙ СЧЁТ: {state.total_score}\n"
        f"📅 ДНЕЙ ЗАВЕРШЕНО: {state.days_completed}\n"
        f"🏆 ДОСТИЖЕНИЙ: {len(state.achievements)}\n\n"
        
        "Стремись к балансу во всех сферах! 🎯"
    )
    
    keyboard = [
        [InlineKeyboardButton("🏆 Мои достижения", callback_data="show_achievements")],
        [InlineKeyboardButton("📤 Поделиться результатом", callback_data="share_progress")],
        [InlineKeyboardButton("🔄 Следующий день", callback_data="next_day")],
        [InlineKeyboardButton("🔄 Начать заново", callback_data="restart")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(text, reply_markup=reply_markup)

async def show_achievements(query, state):
    text = "🏆 ТВОИ ДОСТИЖЕНИЯ\n\n"
    
    all_achievements = [
        {"name": "🎯 Идеальный баланс", "condition": "Получить 5/5 целей за день"},
        {"name": "⚡ Скоростной рекорд", "condition": "Успеть на пару до 18:00"}, 
        {"name": "💼 Карьерист", "condition": "Карьера 8+ очков"},
        {"name": "👨‍👩‍👧‍👦 Суперродитель", "condition": "Семья 8+ очков"},
        {"name": "❤️ Идеальный партнер", "condition": "Не обижать партнера 3 дня подряд"},
        {"name": "🔧 Мастер на все руки", "condition": "Навыки 8+ очков"},
        {"name": "💡 Инноватор", "condition": "Открыть 3+ лайфхака"},
        {"name": "🤝 Настоящий друг", "condition": "Получить помощь друга"},
        {"name": "🕰️ Тайм-менеджер", "condition": "Ни разу не опоздать за 5 дней"},
        {"name": "⚡ Энерджайзер", "condition": "Энергия 8+ очков"},
        {"name": "💰 Финансист", "condition": "Всегда нанимать помощь"},
        {"name": "🚀 Абсолютный чемпион", "condition": "Все показатели 8+ одновременно"}
    ]
    
    unlocked_count = 0
    for achievement in all_achievements:
        achievement_name = achievement["name"].split(" ", 1)[1]
        if any(achievement_name in a for a in state.achievements):
            text += f"✅ {achievement['name']}\n"
            unlocked_count += 1
        else:
            text += f"🔒 {achievement['name']} - {achievement['condition']}\n"
    
    text += f"\n🎯 Прогресс: {unlocked_count}/12 достижений"
    
    keyboard = [
        [InlineKeyboardButton("📊 Назад к статистике", callback_data="show_stats")],
        [InlineKeyboardButton("📤 Поделиться прогрессом", callback_data="share_progress")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text(text, reply_markup=reply_markup)

async def start_new_day(query, state):
    state.day += 1
    state.hours = 15
    state.minutes = 0
    
    # Сохраняем прогресс, но с небольшим снижением
    state.career = max(0, state.career - 1)
    state.family = max(0, state.family - 1)
    state.energy = min(10, state.energy + 2)
    state.skills = max(0, state.skills - 1)
    
    await start_day_message(query, state)

async def final_scene(query, state):
    # ФИНАЛЬНЫЕ РАСЧЕТЫ
    state.days_completed += 1
    state.total_score = calculate_total_score(state)
    
    # ОЦЕНКА РЕЗУЛЬТАТА - ИСПРАВЛЕННЫЕ ПОРОГИ
    time_score = not is_late(state)
    work_score = state.career >= 5  # 5+ для успеха по работе
    family_score = state.family >= 5  # 5+ для успеха по семье
    energy_score = state.energy >= 4  # 4+ для энергии
    skills_score = state.skills >= 3  # 3+ для навыков
    
    total_success = sum([time_score, work_score, family_score, energy_score, skills_score])
    
    # ТЕКСТ РЕЗУЛЬТАТА
    if is_late(state):
        text = f"🕒 {time_to_str(state)} - ❌ ОПОЗДАЛ НА ПАРУ!\n\n"
    else:
        text = f"🕒 {time_to_str(state)} - ✅ УСПЕЛ НА ПАРУ!\n\n"
        if "Скоростной рекорд" not in state.achievements and state.hours <= 18:
            state.achievements.append("Скоростной рекорд")
    
    text += "📊 ИТОГИ ДНЯ:\n\n"
    
    # ДЕТАЛЬНАЯ СТАТИСТИКА
    results = [
        f"{'✅' if time_score else '❌'} Время: {'Успел на пару' if time_score else 'Опоздал'}",
        f"{'✅' if work_score else '❌'} Работа: {'Карьера в порядке' if work_score else 'Проблемы на работе'}",
        f"{'✅' if family_score else '❌'} Семья: {'Семья счастлива' if family_score else 'Семья обижена'}", 
        f"{'✅' if energy_score else '❌'} Энергия: {'Силы есть' if energy_score else 'Нужен отдых'}",
        f"{'✅' if skills_score else '❌'} Навыки: {'Развиваешься' if skills_score else 'Можно лучше'}"
    ]
    
    text += "\n".join(results) + "\n\n"
    
    # МОТИВАЦИОННЫЕ ФРАЗЫ
    motivational_phrases = {
        5: "🏆 LEGENDARY BALANCE!\nТы — бог многозадачности! Этот результат стоит показать всем!",
        4: "🔥 ПОЧТИ ИДЕАЛ!\nОтличный баланс! Друзья будут завидовать твоим навыкам!",
        3: "💪 СОЛИДНЫЙ РЕЗУЛЬТАТ!\nТы держишь всё под контролем! Продолжай в том же духе!",
        2: "📈 ЕСТЬ КУДА РАСТИ!\nНеплохо, но можно лучше! Завтра будет новый шанс!",
        1: "🌱 НАЧАЛО ПУТИ!\nБаланс — это искусство! С каждой попыткой будет получаться лучше!",
        0: "🔄 УЧЕБНЫЙ ДЕНЬ!\nЗавтра будет новый шанс проявить себя!"
    }
    
    text += motivational_phrases.get(total_success, "🎯 Интересный результат!")
    
    if total_success == 5:
        if "Идеальный баланс" not in state.achievements:
            state.achievements.append("Идеальный баланс")
    
    text += f"\n\n🎯 Успешных целей: {total_success}/5"
    text += f"\n⭐ Общий счёт: {state.total_score}"
    text += f"\n🏆 Достижений: {len(state.achievements)}/12"
    
    # ОБНОВЛЯЕМ ДОСТИЖЕНИЯ
    achievement_map = [
        (state.career >= 8, "Карьерист"),
        (state.family >= 8, "Суперродитель"),
        (state.energy >= 8, "Энерджайзер"),
        (state.skills >= 8, "Мастер на все руки"),
        (all([state.career >= 8, state.family >= 8, state.energy >= 8, state.skills >= 8]), "Абсолютный чемпион")
    ]
    
    for condition, achievement in achievement_map:
        if condition and achievement not in state.achievements:
            state.achievements.append(achievement)
    
    # КНОПКА ШАРИНГА
    reply_markup = await share_results_button(query, state)
    
    await query.message.reply_text(text, reply_markup=reply_markup)

# ========== КОМАНДА СТАТУСА ==========
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Бот 'Гонка до Универа' работает корректно!")

# ========== ЗАПУСК БОТА ==========
def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    print("🎮 Бот ГОНКА ДО УНИВЕРА запущен! Готов к использованию!")
    print("📍 Для проверки работы используй команду /status")
    application.run_polling()

if __name__ == "__main__":
    main()