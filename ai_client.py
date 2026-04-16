# ai_client.py
# Асинхронный клиент для DeepSeek API с улучшенной обработкой ошибок.

import os
from openai import AsyncOpenAI, APIError, APIConnectionError, RateLimitError, AuthenticationError
from dotenv import load_dotenv

load_dotenv()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    raise ValueError("DEEPSEEK_API_KEY не найден в .env")

# Асинхронный клиент
client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

SYSTEM_PROMPT = """
Ты – психологический помощник в стиле гештальт-терапии и КПТ.
Правила:
- Не ставь диагнозы, не назначай лекарства.
- Задавай уточняющие вопросы, помогай осознавать чувства и мысли.
- Отвечай эмпатично, на русском языке.
- Если пользователь говорит о суициде или кризисе, мягко предложи обратиться к специалисту (телефон доверия 8-800-2000-122).
"""


async def get_ai_response(messages_history: list) -> str:
    """
    Отправляет историю диалога в DeepSeek и возвращает ответ ассистента.
    В случае ошибок API возвращает понятное сообщение для пользователя.
    """
    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages_history

    try:
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=full_messages,
            temperature=0.7,
            max_tokens=1000
        )
        return response.choices[0].message.content

    except AuthenticationError:
        # Неверный API-ключ – критично, логируем, но пользователю не раскрываем детали
        print("❌ Критическая ошибка: неверный DEEPSEEK_API_KEY")
        return "⚠️ Ошибка конфигурации сервера. Пожалуйста, сообщите администратору."

    except RateLimitError:
        return "⚠️ Слишком много запросов. Пожалуйста, подождите немного и попробуйте снова."

    except APIConnectionError:
        return "⚠️ Проблемы с подключением к серверу ИИ. Проверьте интернет или повторите позже."

    except APIError as e:
        # Любая другая ошибка API (например, 500)
        print(f"❌ API Error: {e}")
        return "⚠️ Ошибка на стороне сервера ИИ. Попробуйте позже."


async def create_summary(messages: list) -> str:
    """
    Создаёт краткую суммаризацию диалога через DeepSeek API.
    messages – список словарей [{"role": "user", "content": "..."}, ...]
    """
    summary_prompt = """Ты — психологический помощник. Перед тобой диалог с пользователем.
Создай КРАТКУЮ выжимку этого диалога (3-5 предложений):
- Основные проблемы и переживания пользователя
- Темы, которые обсуждались
- Что помогло или не помогло
- Важные детали для продолжения работы

Пиши от третьего лица ("Пользователь переживает из-за...").
Будь лаконичен, но сохрани суть."""

    try:
        conversation_text = "\n".join([
            f"{msg['role'].upper()}: {msg['content']}" for msg in messages
        ])

        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": summary_prompt},
                {"role": "user", "content": f"Диалог для суммаризации:\n\n{conversation_text}"}
            ],
            temperature=0.3,
            max_tokens=300
        )
        return response.choices[0].message.content

    except Exception as e:
        # Для суммаризации менее критично, оставляем общий обработчик,
        # но логируем ошибку.
        print(f"❌ Ошибка создания суммаризации: {e}")
        return "[Ошибка создания суммаризации]"
