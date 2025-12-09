BOT_CONFIG = {
    'telegram_channel': 'https://t.me/chibeki_official',
    'max_market_price': 9999,
    'min_market_price': 15,
    'market_items_per_page': 8,
    'market_create_per_page': 6
}

BOT_TEXTS = {
    'already_started': "ℹ️ Ты уже запустил бота. Кстати за багоюз у нас дают бан",
    'welcome': """⚡️*Хей, {name}!*
Вижу, ты новичок у нас? Что ж, вероятно ты здесь, потому что любишь _коллекционировать ЧИБИКОВ, да?_
Будем считать, что я угадал. В любом случае, раз ты тут впервые, я тебя задобрю, и это ни в коем случае не чтобы ты тут подольше остался, даже не думай! Я очень щедр, и начислю тебе *🧧 ЧИБИ-ПАК!* Ты можешь найти и открыть его в *меню*. Также советую ознакомиться с остальными командами бота, ты тут надолго и они тебе точно пригодятся! Удачного пути, и хороших ЧИБИКОВ!""",
    'rate_limit': "⚡️ *Слишком много запросов!* Подожди немного.",
    'ban_message': "🤡 *Ты в бане!* Ты снова получишь доступ к боту через *{days_left}* дней.",
    'market_welcome': "🛍️ *Рынок чибиков*\n_Добро пожаловать на рынок! Здесь можно как купить, так и продать своих чибиков. Удобная штука!_\n_•••••••••••••••••_\nЛотов: *{total_lots}*",
    'market_empty': "✨ Лотов нет",
    'market_lot_view': "🛍️ *Лот игрока {seller_name}*\n_•••••••••••••••••_\n{chibi_name} за 💰{price} коинов\n_•••••••••••••••••_\n_Хочешь купить?_",
    'market_buy_success': "⚡️ Воу, *{buyer_name}* купил *{chibi_name}* у *{seller_name}* за *💰{price}* коинов!",
    'market_create_select': "🛍️ *Создаем лот*\n_Отличная идея! Выбери чибика, которого хочешь продать_",
    'market_create_empty': "✨ Пусто",
    'market_create_set_price': "🛍️ *Создаем лот*\n_Супер! А теперь отправь мне цену, за которую хочешь продать {chibi_name}_",
    'market_price_too_low': "🤷‍♂️ Нет, друг! Минимальная цена - 15!",
    'market_price_too_high': "🤷‍♂️ Слишком дорого! Ты там не зажрался, дружище?",
    'market_create_confirm': "🛍️ *Создаем лот?*\n_Проверь все, чтобы не получилось недоразумений! После покупки чибика другим игроком ты его уже не вернешь_\n_•••••••••••••••••_\nТы отдаешь *{chibi_name}* за 💰*{price}*!",
    'market_lot_created': "✅ Лот успешно выставлен на рынок!",
    'market_lot_canceled': "❌ Лот отменен",
    'market_not_enough_coins': "💰 *Недостаточно коинов!*",
    'market_own_lot': "🙅‍♂️ *Нельзя купить свой же лот!*",
    'market_lot_removed': "🗑️ *Лот удален с рынка*",
    'market_no_chibis': "🎒 *У тебя нет чибиков для продажи!*",
    'market_already_listed': "📌 *Этот чибик уже выставлен на рынке!*",
    'not_yours': "🙈 *Не твое!*",
    'connection_lost': "⛓️‍💥* Потеряно соединение!* Попробуй снова!"
}

BOT_SETTINGS = {
    'test_users': ['ya_admin7', 'tmkazavr'],
    'max_reqs_per_min': 30,
    'chibi_cooldown': 3 * 3600,
    'task_completed_cooldown': 4 * 3600,
    'task_skipped_cooldown': 5.5 * 3600,
    'max_bet': 10000,
    'min_bet': 1,
    'chibi_pack_price': 120,
    'pack_secret_chance': 0.05,
    'task_min_reward': 32,
    'task_max_reward': 49,
    'bonus_min': 7,
    'bonus_max': 19
}

STICKERS = {
    'welcome': "CAACAgIAAxkBAAE9JsNpAzQZv6b4b-KZ3ftL2Sld0kUjDQAC400AAkuWEEosjitzZk8fzDYE",
    'already_started': "CAACAgIAAxkBAAE9JstpAzTQNnpt9KcoUte9P7K3CiHpswACmEQAAk-mEEqVynQKXagSVjYE",
    'task_complete': "CAACAgIAAxkBAAE9Js9pAzTWs9gLLtl9Gqz_9V_4sbwXqgAC7EYAAjNREEqhVSL_nxyHZTYE",
    'gift_sent': "CAACAgIAAxkBAAE9JtFpAzTjbRJ884hA4YNjTqPc7Z05lAACQEgAAlZVEUqWc8vDGvLqWTYE",
    'gift_received': "CAACAgIAAxkBAAE9OxxpBRLZ5OANTuRD-97sRPdCONwv0AACU0YAAkVlEErI0vjxKMrHnTYE"
}

RARITY_EMOJIS = {
    'Common': '🔷',
    'Secret': '🔶',
    'Prize': '♦️'
}
