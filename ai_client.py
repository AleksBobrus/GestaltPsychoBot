# ai_client.py – вызов DeepSeek API

import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    raise ValueError("DEEPSEEK_API_KEY не найден в .env")

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

SYSTEM_PROMPT = """
Ты – психологический помощник в стиле гештальт-терапии и КПТ.
Правила:
- Не ставь диагнозы, не назначай лекарства.
- Задавай уточняющие вопросы, помогай осознавать чувства и мысли.
- Отвечай эмпатично, на русском языке.
- Если пользователь говорит о суициде или кризисе, мягко предложи обратиться к специалисту (телефон доверия 8-800-2000-122).
"""

def get_ai_response(messages_history: list) -> str:
    """
    Отправляет историю сообщений в DeepSeek и возвращает ответ.
    messages_history – список словарей [{"role": "user", "content": "..."}, ...]
    """
    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages_history
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=full_messages,
            temperature=0.7,
            max_tokens=1000
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Ошибка DeepSeek API: {e}")
        return "😔 Извините, сейчас я не могу ответить. Попробуйте позже или обратитесь в поддержку."