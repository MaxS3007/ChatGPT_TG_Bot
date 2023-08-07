import os
import threading
import time

import telebot
import openai
import logging
import sqlite3
import atexit
from config import *


openai.api_key = OPENAI_API_KEY

# Create logger for bot
logging.basicConfig(filename='bot.log', level=logging.INFO)

# Список идентификаторов пользователей, которым разрешен доступ
# Получить значение переменной окружения ALLOWED_USERS
allowed_users = ALLOWED_USERS

MODELS_GPT = "text-davinci-003"
N_PARAM = 3
STOP = None
TEMPERATURE = 0.5
MAX_TOKEN = 3500



# Mutex
lock = threading.Lock()

# Временной интервал для ограничения скорости
RATE_LIMIT_INTERVAL = 5 * 60  #  min

# Время последнего запроса
last_request_time = time.time()

MAX_MESSAGE_LENGTH = 4096

# Функция декоратора для проверки доступа
def restricted_access(func):
    def wrapper(message):
        user_id = message.from_user.id
        if user_id in ALLOWED_USERS:
            return func(message)
        else:
            bot.reply_to(message, "У вас нет доступа к этому боту.")

    return wrapper


# Создайте локальную переменную для каждого потока
thread_local = threading.local()


# Создайте функцию для извлечения объекта подключения к базе данных для текущего потока
def get_conn():
    if not hasattr(thread_local, "conn"):
        thread_local.conn = sqlite3.connect('context.db')
    return thread_local.conn


# Создайте таблицу для хранения контекста запроса
with get_conn() as conn:
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS context
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, text TEXT)''')
    conn.commit()

# Создание кэша для хранения контекста запроса
HOT_CACHE_DURATION = 5 * 60  # 5 min
hot_cache = {}


# # создаем подключение к базе данных
# conn = sqlite3.connect("example.db", check_same_thread=False)
#
# # создаем таблицу в базе данных для хранения контекста
# with conn:
#     cur = conn.cursor()
#     cur.execute("CREATE TABLE IF NOT EXISTS context (user_id TEXT, message TEXT, timestamp TEXT)")
#
# # задаем интервал, через который массив с контекстом будет очищаться
# CONTEXT_CACHE_INTERVAL = timedelta(minutes=10)
#
# # словарь, в котором будут храниться последние запросы пользователя
# context_cache = {}

bot = telebot.TeleBot(TOKEN)
print("Бот запущен...")

# Обработчик команды /start и обновите горячий кэш при запуске бота
@bot.message_handler(commands=['start'])
@restricted_access
def start(message):
    bot.reply_to(message, "Привет, я ваш помощник, готовый работать с OpenAI API! (ChatGPT)")
    user_id = message.from_user.id
    # When the bot starts, look for the context in the database to recover the conversation.
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT text FROM context WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
        row = c.fetchone()
        if row is not None:
            hot_cache[user_id] = (row[0], time.time())


# Обработчик пользовательских сообщений
@bot.message_handler(func=lambda message: message.text is not None and message.text[0] != '/')
@restricted_access
def echo_message(message):
    try:
        text = message.text
        user_id = message.from_user.id
        prompt = ""

        # Проверьте, не отправил ли пользователь слишком много сообщений за короткий промежуток времени
        global last_request_time


        # Извлеките последний сохраненный контекст запроса для данного пользователя из горячего кэша
        prev_text, prev_time = hot_cache.get(user_id, (None, 0))

        # Если запись находится в кэше и время отправки запроса не превышает 5 минут, используйте ее в качестве
        # предыдущего контекста
        if prev_text and time.time() - prev_time < HOT_CACHE_DURATION:
            print("Берем данные из кэша ======================")
            prompt = prev_text + '\n' + text
            print(prompt)
            print("===========================================")

        else:
            # В противном случае запросите базу данных, чтобы получить контекст последнего запроса для этого пользователя
            with get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT text FROM context WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
                row = c.fetchone()
                prompt = row[0] + '\n' + text if row is not None else text

                # Обновление кэша
                hot_cache[user_id] = (prompt, time.time())
                print("Берем данные из БАЗЫ ДАННЫХ <>==<>==<>==<>==<>==<>==<>==<>==<>==<>==<>==<>==<>")
                print(prompt)
                print("^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^")


        bot.reply_to(message, "Запрос принят к обработке, пожалуйста, подождите.")

        response = {}
        if prompt:
        # Генерация ответа с помощью OpenAI
            response = response_to_gpt(prompt)

        response_text = "Запрос не обработан. Повторите через 1 минуту"
        u = False
        print(response)
        if response:
            # Разделение ответа на несколько сообщений, если его длина превышает максимальную, разрешенную Telegram API
            print()
            print()
            print("============ ОТВЕТ ИИ =====================================================================================================")
            response_text = ""
            u = True
            for choice in response['choices']:
                print(choice['text'])
                print("=================================")
                response_text += choice['text'] + "\n=================================\n"
            print("============ ОТВЕТ ИИ =====================================================================================================")
            print()
            print()

        #response_text = response.choices[0].text

        while len(response_text) > 0:
            response_chunk = response_text[:MAX_MESSAGE_LENGTH]
            response_text = response_text[MAX_MESSAGE_LENGTH:]
            # Отвеччем пользователю текущим фрагментом ответа
            bot.reply_to(message, response_chunk)

        # Сохраните контекст запроса в базе данных
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO context (user_id, text) VALUES (?, ?)", (user_id, text))
            conn.commit()

    except Exception as e:
        logging.error(str(e))
        bot.reply_to(message, f"При обработке запроса произошла ошибка. Пожалуйста, попробуйте еще раз позже. \n {e} ")
        drop_cache(message)

"""
MODELS_GPT = "text-davinci-003"
N_PARAM = 3
STOP = None
TEMPERATURE = 0.5
MAX_TOKEN = 3500
"""


def response_to_gpt(message):
    response = openai.Completion.create(
        model=MODELS_GPT,
        prompt=message,
        n=N_PARAM,
        stop=STOP,
        max_tokens=MAX_TOKEN,
        temperature=TEMPERATURE,

    )
    return response


# Добавьте обработчик команды /help
@bot.message_handler(commands=['help'])
def help_message(message):
    bot.reply_to(message,"Вы можете отправлять запросы в Openal API через меня. Просто напишите мне свой запрос в тексте, и я отправлю его для обработки.\n\n/drop_cache - очистка кэша беседы")

# Добавьте обработчик команды /help
@bot.message_handler(commands=['settings'])
def help_message(message):
    bot.reply_to(message,f"Параметры OpenAI:\nMODELS_GPT = {MODELS_GPT}\nN = {N_PARAM}\nSTOP = {STOP}\nTEMPERATURE = {TEMPERATURE}\nMAX_TOKEN = {MAX_TOKEN}")


@bot.message_handler(commands=['drop_cache'])
@restricted_access
def drop_cache(message):
    user_id = message.from_user.id
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM context WHERE user_id=?', (user_id,))
    hot_cache.clear()
    conn.commit()
    bot.send_message(user_id, "Кэш удален.")


# Добавьте функцию, которая будет вызываться при выходе для закрытия подключения к базе данных
def close_conn():
    conn = getattr(thread_local, "conn", None)
    if conn is not None:
        conn.close()


# Зарегистрируйте функцию, которая будет вызываться при выходе
atexit.register(conn.close)

if __name__ == "__main__":
    bot.polling(none_stop=True)




























# def serch(prompt):
#
#     model_engine = "text-davinci-003"
#
#     if 'exit' in prompt or 'quit' in prompt:
#         return 0
#
#     completion = openai.Completion.create(
#         engine=model_engine,
#         prompt=prompt,
#         max_tokens=3500,
#         n=1,
#         stop=None,
#         temperature=0.5,
#     )
#     response = completion.choices[0].text
#     #print(len(response))
#     return response
#
#
#
#
# # создаем обработчик команд
# @bot.message_handler(commands=['start'])
# def start(message):
#     bot.reply_to(message, "Привет! Я бот, который может помочь вам работать с OpenAI")
#
#
# @bot.message_handler(commands=['help'])
# def help(message):
#     bot.reply_to(message,
#                  "Вы можете отправлять запросы в OpenAI API через меня. Просто напишите мне свой запрос и я отправлю его на обработку.")
#
#
# @bot.message_handler(content_types=['text'])
# def start(message):
#
#     # смотрим, есть ли контекст в кэше
#     if message.chat.id in context_cache and datetime.now() - context_cache[message.chat.id]['timestamp'] <= CONTEXT_CACHE_INTERVAL:
#         context = context_cache[message.chat.id]['message']
#     else:
#         # если контекста в кэше нет, ищем его в базе данных
#         with conn:
#             cur = conn.cursor()
#             cur.execute("SELECT message FROM context WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1",
#                         (str(message.chat.id),))
#             row = cur.fetchone()
#             context = row[0] if row else ""
#
#     bot.reply_to(message, "Запрос принят в работу.")
#     try:
#         mes = context + message.text
#         print("Запрос (с учетом беседы):\n"+mes)
#         ans = serch(mes)
#         lt = 4096
#         for t in range(0, len(ans), lt):
#             print(ans[t:t + lt])
#             bot.send_message(message.from_user.id, ans[t:t + lt])
#
#         # сохраняем контекст в кэше и базе данных
#         with conn:
#             cur = conn.cursor()
#             cur.execute("INSERT INTO context (user_id, message, timestamp) VALUES (?, ?, ?)",
#                         (str(message.chat.id), context + message.text, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
#             conn.commit()
#         context_cache[message.chat.id] = {'message': context + message.text, 'timestamp': datetime.now()}
#
#     except:
#             bot.reply_to(message, "Произошла ошибка при обработке вашего запроса.")
#
#
# bot.polling(none_stop=True, interval=0)
