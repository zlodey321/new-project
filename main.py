
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional
from functools import wraps

import requests
from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.error import TelegramError

# Загрузка переменных окружения
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
KP_API_KEY = os.getenv("KINOPOISK_API_KEY")

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация API
API_URL = "https://api.kinopoisk.dev/v1.3/movie"
HEADERS = {"X-API-KEY": KP_API_KEY}

# Состояния для ConversationHandler
TITLE, GENRE, LIMIT = range(3)

def async_error_handler(func):
    """Декоратор для обработки исключений в асинхронных функциях"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {str(e)}")
    return wrapper

class MovieBot:
    def __init__(self):
        self.application = Application.builder().token(TOKEN).build()
        self._register_handlers()

    def _register_handlers(self):
        """Регистрация обработчиков команд"""
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("movie_search", self.movie_search)],
            states={
                TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.set_title)],
                GENRE: [CallbackQueryHandler(self.set_genre)],
                LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.set_limit)]
            },
            fallbacks=[CommandHandler("cancel", self.cancel)]
        )

        self.application.add_handler(conv_handler)
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("history", self.show_history))

    @async_error_handler
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /start"""
        text = (
            "🎬 Добро пожаловать в MovieFinder!\n"
            "Доступные команды:\n"
            "/movie_search - Поиск по названию\n"
            "/movie_by_rating - Поиск по рейтингу\n"
            "/low_budget_movie - Фильмы с низким бюджетом\n"
            "/high_budget_movie - Фильмы с высоким бюджетом\n"
            "/history - История поиска"
        )
        await update.message.reply_text(text)

    @async_error_handler
    async def movie_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Инициализация поиска фильмов"""
        context.user_data.clear()
        keyboard = [
            [InlineKeyboardButton("Указать название", callback_data="set_title")],
            [InlineKeyboardButton("Выбрать жанр", callback_data="set_genre")],
            [InlineKeyboardButton("Количество результатов", callback_data="set_limit")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Выберите параметры поиска:", reply_markup=reply_markup)
        return TITLE

    async def set_title(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Сохранение названия фильма"""
        context.user_data["title"] = update.message.text
        await update.message.reply_text("Название сохранено. Выберите следующий параметр.")
        return GENRE

    async def set_genre(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Обработка выбора жанра"""
        query = update.callback_query
        await query.answer()
        context.user_data["genre"] = query.data
        await query.edit_message_text(f"Выбран жанр: {query.data}")
        return LIMIT

    async def set_limit(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Сохранение лимита результатов"""
        try:
            limit = int(update.message.text)
            if 1 <= limit <= 20:
                context.user_data["limit"] = limit
                await self._perform_search(update, context)
                return ConversationHandler.END
            raise ValueError
        except ValueError:
            await update.message.reply_text("Введите число от 1 до 20")
            return LIMIT

    async def _perform_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Выполнение поиска и отправка результатов"""
        params = {
            "name": context.user_data.get("title", ""),
            "genres.name": context.user_data.get("genre", ""),
            "limit": context.user_data.get("limit", 5)
        }
        
        movies = await self._fetch_movies(params)
        if not movies:
            await update.message.reply_text("Фильмы не найдены")
            return

        self._save_to_history(context, movies)
        await self._send_results(update, movies)

    async def _fetch_movies(self, params: Dict) -> List[Dict]:
        """Асинхронный запрос к API"""
        try:
            async with requests.AsyncClient() as client:
                response = await client.get(API_URL, headers=HEADERS, params=params)
                response.raise_for_status()
                return response.json().get("docs", [])
        except Exception as e:
            logger.error(f"API Error: {str(e)}")
            return []

    def _save_to_history(self, context: ContextTypes.DEFAULT_TYPE, movies: List[Dict]) -> None:
        """Сохранение в историю"""
        history = context.user_data.get("history", [])
        history.extend([
            {
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "title": movie.get("name"),
                "rating": movie.get("rating", {}).get("kp"),
                "year": movie.get("year"),
                "genres": [g["name"] for g in movie.get("genres", [])],
                "poster": movie.get("poster", {}).get("url")
            } for movie in movies
        ])
        context.user_data["history"] = history[-50:]  # Храним последние 50 записей

    async def _send_results(self, update: Update, movies: List[Dict]) -> None:
        """Отправка результатов с пагинацией"""
        # Реализация пагинации через InlineKeyboardPaginator
        pass

    async def show_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показ истории поиска"""
        history = context.user_data.get("history", [])
        if not history:
            await update.message.reply_text("История поиска пуста.")
            return

        # Реализация пагинации и форматирования
        pass

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Отмена текущего диалога"""
        await update.message.reply_text("Поиск отменен")
        context.user_data.clear()
        return ConversationHandler.END

    def run(self):
        """Запуск бота"""
        self.application.run_polling()

if __name__ == "__main__":
    bot = MovieBot()
    bot.run()
