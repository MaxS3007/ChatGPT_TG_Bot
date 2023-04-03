import telebot
import openai
from config import *


openai.api_key = OPENAI_API_KEY


def serch(prompt):

    model_engine = "text-davinci-003"

    if 'exit' in prompt or 'quit' in prompt:
        return 0

    completion = openai.Completion.create(
        engine=model_engine,
        prompt=prompt,
        max_tokens=3596,
        n=1,
        stop=None,
        temperature=0.5,
    )
    response = completion.choices[0].text
    print(len(response))
    return response


bot = telebot.TeleBot(TOKEN)
print("Бот запущен...")

@bot.message_handler(content_types=['text'])
def start(message):
    mes = message.text
    print("Запрос:\n"+mes)
    ans = serch(mes)
    lt = 4096
    for t in range(0, len(ans), lt):
        print(ans[t:t + lt])
        bot.send_message(message.from_user.id, ans[t:t + lt])


bot.polling(none_stop=True, interval=0)
