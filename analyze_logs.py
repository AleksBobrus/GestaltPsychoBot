# analyze_logs.py
# Скрипт для анализа лог-файла bot_public.log.
# Подсчитывает общее количество записей, ошибок, предупреждений,
# число регистраций новых пользователей, реферальных бонусов
# и текущее значение глобального счётчика ИИ-сообщений.

import re

LOG_FILE = "bot_public.log"

def analyze():
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()

    total_lines = len(lines)
    errors = []
    warnings = []
    registrations = 0
    ai_messages = 0
    last_counter = 0
    referral_bonuses = 0

    # Универсальный шаблон для глобального счётчика (не привязан к конкретному лимиту)
    counter_pattern = re.compile(r"Глобальный счётчик ИИ-сообщений: (\d+) / \d+")

    # Шаблон для обнаружения факта регистрации ("начислено пользователю ...")
    reg_pattern = re.compile(r"начислено пользователю \d+")

    # Шаблон для реферальных бонусов ("Бонусные X дней подписки начислены пригласившему ...")
    ref_pattern = re.compile(r"Бонусные \d+ дней подписки начислены пригласившему \d+ за \d+")

    for line in lines:
        if "ERROR" in line:
            errors.append(line.strip())
        if "WARNING" in line:
            warnings.append(line.strip())
        if reg_pattern.search(line):
            registrations += 1
        if ref_pattern.search(line):
            referral_bonuses += 1
        match = counter_pattern.search(line)
        if match:
            ai_messages = int(match.group(1))
            last_counter = ai_messages

    print("=" * 55)
    print(f"📊 АНАЛИЗ ЛОГ-ФАЙЛА ({LOG_FILE})")
    print("=" * 55)
    print(f"Всего записей: {total_lines}")
    print(f"Ошибок (ERROR): {len(errors)}")
    print(f"Предупреждений (WARNING): {len(warnings)}")
    print(f"Регистраций новых пользователей: {registrations}")
    print(f"Начислено реферальных бонусов: {referral_bonuses}")
    print(f"Текущий глобальный счётчик ИИ: {last_counter} / 800")
    print("=" * 55)

    if errors:
        print("\n🔴 Последние 3 ошибки:")
        for err in errors[-3:]:
            print(f"  - {err}")

    if warnings:
        print("\n🟡 Последние 3 предупреждения:")
        for warn in warnings[-3:]:
            print(f"  - {warn}")

if __name__ == "__main__":
    analyze()
