import os
import re
import asyncio
from typing import Dict, Tuple, List, Optional

import httpx
from fastapi import FastAPI, Request, Response
from pydantic import BaseModel

# === Конфигурация ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("Environment variable BOT_TOKEN is required")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"  # уникальный путь для вебхука
APP_NAME = "ScoreBot"

# Алиасы имён → каноническое имя
ALIASES = {
    "paul": "Paul",
    "pavlo": "Paul",
    "roman": "Roman",
    "roma": "Roman",
}

# Паттерн: находит «имя +число» (допускает «:», «-», лишние пробелы, переносы строк)
# Поддерживает + и - (минус), а также отсутствие знака (считаем как +)
SCORE_REGEX = re.compile(
    r"(?i)\b(paul|pavlo|roman|roma)\b\s*[:\-–—]?\s*([+\-−])?\s*(\d+)\b"
)

app = FastAPI(title=APP_NAME)

# Память очков в рамках живого процесса (без привязки к аккаунтам/чату)
# Хранение по chat_id: {'Paul': int, 'Roman': int}
SCORES: Dict[int, Dict[str, int]] = {}


# === Утилиты ===
def normalize_name(alias: str) -> str:
    return ALIASES.get(alias.lower(), alias)


def parse_scores(text: str) -> List[Tuple[str, int]]:
    """Возвращает список (canonical_name, delta)."""
    results: List[Tuple[str, int]] = []
    for m in SCORE_REGEX.finditer(text):
        raw_name, raw_sign, raw_value = m.group(1), m.group(2), m.group(3)
        name = normalize_name(raw_name)
        sign = raw_sign or "+"  # если знак не указан — считаем как плюс
        sign = "-" if sign in ("-", "−") else "+"  # нормализуем минус из разных символов
        value = int(raw_value)
        delta = -value if sign == "-" else value
        results.append((name, delta))
    return results


def get_or_init_chat_scores(chat_id: int) -> Dict[str, int]:
    if chat_id not in SCORES:
        SCORES[chat_id] = {"Paul": 0, "Roman": 0}
    # Гарантия, что обе ключевые записи есть
    SCORES[chat_id].setdefault("Paul", 0)
    SCORES[chat_id].setdefault("Roman", 0)
    return SCORES[chat_id]


def format_total(chat_id: int) -> str:
    scores = get_or_init_chat_scores(chat_id)
    return (
        "🎯 Total Score:\n"
        f"Paul: {scores['Paul']}\n"
        f"Roman: {scores['Roman']}"
    )


async def tg_request(method: str, payload: Dict) -> Dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{TELEGRAM_API}/{method}", json=payload)
        r.raise_for_status()
        return r.json()


async def send_message(chat_id: int, text: str, reply_to: Optional[int] = None) -> None:
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_to:
        payload["reply_to_message_id"] = reply_to
        payload["allow_sending_without_reply"] = True
    await tg_request("sendMessage", payload)


# === Служебные эндпоинты ===

@app.get("/healthz")
async def healthz():
    return {"status": "ok", "app": APP_NAME}


@app.get("/set_webhook")
async def set_webhook(request: Request, url: Optional[str] = None):
    """
    Устанавливает вебхук на текущий Render URL или на ?url=...
    1) Если передан ?url=..., используем его.
    2) Иначе пытаемся взять PUBLIC_URL или RENDER_EXTERNAL_URL из env.
    3) Иначе строим по заголовкам запроса.
    """
    base = (
        url
        or os.getenv("PUBLIC_URL", "").strip()
        or os.getenv("RENDER_EXTERNAL_URL", "").strip()
    )
    if not base:
        # Собираем из запроса (на случай, если переменных нет)
        host = request.headers.get("x-forwarded-host") or request.url.netloc
        scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
        base = f"{scheme}://{host}"

    target = base.rstrip("/") + WEBHOOK_PATH
    resp = await tg_request("setWebhook", {
        "url": target,
        "allowed_updates": ["message"],  # нам достаточно сообщений
        "drop_pending_updates": False
    })
    return {"set_webhook_to": target, "telegram_response": resp}


@app.get("/delete_webhook")
async def delete_webhook():
    resp = await tg_request("deleteWebhook", {"drop_pending_updates": False})
    return {"deleted": True, "telegram_response": resp}


# === Telegram вебхук ===

class TGChat(BaseModel):
    id: int


class TGFrom(BaseModel):
    id: int
    is_bot: bool = False
    first_name: Optional[str] = None
    username: Optional[str] = None


class TGMessage(BaseModel):
    message_id: int
    chat: TGChat
    from_: Optional[TGFrom] = None
    text: Optional[str] = None

    class Config:
        fields = {"from_": "from"}


class TGUpdate(BaseModel):
    update_id: int
    message: Optional[TGMessage] = None


@app.post(WEBHOOK_PATH)
async def telegram_webhook(update: TGUpdate):
    """
    Основная логика:
    - /start: инструкция
    - /score: показать текущий счёт
    - /clear: обнулить счёт
    - Любое сообщение формата "Paul +2" / "Pavlo +2" / "Roman +4" / "Roma -1" и т.д. — добавляет/вычитает очки
      (в одном сообщении может быть несколько строк/упоминаний).
    - После изменения очков бот присылает общий счёт.
    """
    msg = update.message
    if not msg or not msg.text:
        return Response(status_code=200)

    chat_id = msg.chat.id
    text = msg.text.strip()

    # Команды
    if text.startswith("/start"):
        help_text = (
            "Привет! Я считаю очки Paul/Pavlo и Roman/Roma в этом чате.\n\n"
            "Примеры сообщений учителя:\n"
            "  • Paul +2\n"
            "  • Roman +4\n"
            "  • Roman +4\\nPaul +2 (в одном сообщении — несколько строк)\n\n"
            "Команды:\n"
            "  • /score — показать текущий счёт\n"
            "  • /clear — обнулить очки\n\n"
            "Важно: в BotFather отключите Privacy Mode, чтобы я видел обычные сообщения в группе."
        )
        await send_message(chat_id, help_text, reply_to=msg.message_id)
        return Response(status_code=200)

    if text.startswith("/score"):
        await send_message(chat_id, format_total(chat_id), reply_to=msg.message_id)
        return Response(status_code=200)

    if text.startswith("/clear"):
        SCORES[chat_id] = {"Paul": 0, "Roman": 0}
        await send_message(chat_id, "The score is reset. Let's start over!\n\n" + format_total(chat_id))
        return Response(status_code=200)

    # Парсинг очков из произвольного текста
    changes = parse_scores(text)
    if changes:
        scores = get_or_init_chat_scores(chat_id)
        for name, delta in changes:
            # Только два игрока, лишние имена игнорируем на всякий случай
            if name in ("Paul", "Roman"):
                scores[name] += delta
        await send_message(chat_id, format_total(chat_id))
        return Response(status_code=200)

    # Ничего релевантного — тихо подтверждаем
    return Response(status_code=200)
