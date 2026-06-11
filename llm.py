"""LLM-парсер заявок через OpenAI GPT-4o.

Возвращает тот же словарь, что и parsing.parse_message, но более устойчиво:
понимает опечатки, неформальные адреса, казахские слова, выводы по контексту.
"""
import json
import logging

from openai import AsyncOpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger("bot")

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI | None:
    global _client
    if not OPENAI_API_KEY:
        return None
    if _client is None:
        _client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _client


SYSTEM_PROMPT = """Ты помощник, который извлекает структурированные данные о заявке \
на доставку из свободного русского/казахского текста и имён прикреплённых файлов.

Поля заявки (все опциональны, если значения нет — верни пустую строку):
- order_number: номер документа/накладной (только цифры, без №)
- doc_date: дата документа в формате DD.MM.YYYY (часто берётся из имени файла после «от»)
- address: адрес доставки. Принимай неформальные формулировки («жетысу рынок», «возле ЦУМа», \
«мкр Алгабас, д 5»). Если в тексте просто название места — это адрес.
- client: ФИО или название клиента. НЕ путать с автором сообщения и не с именем бота.
- phone: телефон в любом формате (нормализуй пробелы)
- desired_time: одно из значений — «сегодня», «завтра» или пусто. \
Казахские слова «бүгін» → «сегодня», «ертең» → «завтра».

Никогда не выдумывай данные, которых нет в исходных материалах. Если сомневаешься — оставляй \
поле пустым."""


# JSON Schema для structured outputs
RESPONSE_SCHEMA = {
    "name": "delivery_order",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "order_number":  {"type": "string"},
            "doc_date":      {"type": "string"},
            "address":       {"type": "string"},
            "client":        {"type": "string"},
            "phone":         {"type": "string"},
            "desired_time":  {"type": "string", "enum": ["сегодня", "завтра", ""]},
        },
        "required": ["order_number", "doc_date", "address", "client", "phone", "desired_time"],
        "additionalProperties": False,
    },
}


async def parse_message_llm(text: str, filenames: list[str] | None = None) -> dict | None:
    """Вызов GPT-4o для извлечения полей заявки.

    Возвращает словарь полей (как parsing.parse_message) с добавленным ключом 'files'.
    None — если API недоступен / ключа нет / запрос упал.
    """
    client = _get_client()
    if client is None:
        return None

    filenames = filenames or []
    user_msg = (
        f"Текст сообщения:\n{text or '(пусто)'}\n\n"
        f"Имена прикреплённых файлов:\n"
        + ("\n".join(f"- {f}" for f in filenames) if filenames else "(нет файлов)")
    )

    try:
        resp = await client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_schema", "json_schema": RESPONSE_SCHEMA},
            temperature=0,
            timeout=15,
        )
        content = resp.choices[0].message.content
        data = json.loads(content)
        data["files"] = filenames
        logger.info("LLM-парсинг: %s", data)
        return data
    except Exception as e:
        logger.warning("LLM parse failed (%s), упадём на regex-парсер", e)
        return None
