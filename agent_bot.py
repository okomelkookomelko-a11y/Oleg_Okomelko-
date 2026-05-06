import os, json, math, logging, httpx
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import anthropic
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

TG_TOKEN = os.getenv("TG_TOKEN")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_KEY")
NOTES_DIR = Path("/home/bot/my-bot/notes")
NOTES_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
conversation_history: dict[int, list] = {}

SYSTEM_PROMPT = """Ти — бізнес-асистент на базі Claude. Відповідай виключно українською мовою.
Ти вмієш: робити математичні розрахунки, зберігати та показувати нотатки,
визначати поточну дату/час, читати веб-сторінки, аналізувати зображення.
Будь чітким, лаконічним, корисним. Якщо питання стосується бізнесу — давай практичні поради."""

TOOLS = [
    {
        "name": "calculate",
        "description": "Виконує математичні розрахунки. Передай Python-вираз як рядок.",
        "input_schema": {
            "type": "object",
            "properties": {"expression": {"type": "string", "description": "Математичний вираз, напр. '2 + 2 * 10'"}},
            "required": ["expression"]
        }
    },
    {
        "name": "save_note",
        "description": "Зберігає нотатку для користувача.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Заголовок нотатки"},
                "content": {"type": "string", "description": "Зміст нотатки"}
            },
            "required": ["title", "content"]
        }
    },
    {
        "name": "list_notes",
        "description": "Повертає список всіх нотаток користувача.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "delete_note",
        "description": "Видаляє нотатку за індексом (1-based).",
        "input_schema": {
            "type": "object",
            "properties": {"index": {"type": "integer", "description": "Номер нотатки зі списку"}},
            "required": ["index"]
        }
    },
    {
        "name": "get_datetime",
        "description": "Повертає поточну дату й час українською мовою.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "read_url",
        "description": "Завантажує та повертає текстовий вміст веб-сторінки.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "URL сторінки"}},
            "required": ["url"]
        }
    }
]

UA_MONTHS = ["січня","лютого","березня","квітня","травня","червня",
              "липня","серпня","вересня","жовтня","листопада","грудня"]
UA_DAYS = ["понеділок","вівторок","середа","четвер","п'ятниця","субота","неділя"]


def tool_calculate(expression: str) -> str:
    try:
        allowed = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
        result = eval(expression, {"__builtins__": {}}, allowed)
        return f"{expression} = {result}"
    except Exception as e:
        return f"Помилка: {e}"


def _notes_file(user_id: int) -> Path:
    return NOTES_DIR / f"{user_id}.json"


def tool_save_note(user_id: int, title: str, content: str) -> str:
    path = _notes_file(user_id)
    notes = json.loads(path.read_text()) if path.exists() else []
    ts = datetime.now().strftime("%d.%m.%Y %H:%M")
    notes.append({"title": title, "content": content, "created": ts})
    path.write_text(json.dumps(notes, ensure_ascii=False, indent=2))
    return f"✅ Нотатку «{title}» збережено."


def tool_list_notes(user_id: int) -> str:
    path = _notes_file(user_id)
    if not path.exists():
        return "Нотаток немає."
    notes = json.loads(path.read_text())
    if not notes:
        return "Нотаток немає."
    lines = [f"{i+1}. **{n['title']}** ({n['created']})\n{n['content']}" for i, n in enumerate(notes)]
    return "\n\n".join(lines)


def tool_delete_note(user_id: int, index: int) -> str:
    path = _notes_file(user_id)
    if not path.exists():
        return "Нотаток немає."
    notes = json.loads(path.read_text())
    if index < 1 or index > len(notes):
        return f"Нотатки #{index} не існує."
    deleted = notes.pop(index - 1)
    path.write_text(json.dumps(notes, ensure_ascii=False, indent=2))
    return f"🗑 Нотатку «{deleted['title']}» видалено."


def tool_get_datetime() -> str:
    now = datetime.now(ZoneInfo("Europe/Kyiv"))
    return (f"{UA_DAYS[now.weekday()]}, {now.day} {UA_MONTHS[now.month-1]} {now.year} р., "
            f"{now.strftime('%H:%M')} (Київ)")


def tool_read_url(url: str) -> str:
    try:
        r = httpx.get(url, timeout=15, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ").split())
        return text[:4000] if text else "Не вдалося отримати текст."
    except Exception as e:
        return f"Помилка завантаження: {e}"


def execute_tool(name: str, inputs: dict, user_id: int) -> str:
    if name == "calculate":
        return tool_calculate(inputs["expression"])
    if name == "save_note":
        return tool_save_note(user_id, inputs["title"], inputs["content"])
    if name == "list_notes":
        return tool_list_notes(user_id)
    if name == "delete_note":
        return tool_delete_note(user_id, inputs["index"])
    if name == "get_datetime":
        return tool_get_datetime()
    if name == "read_url":
        return tool_read_url(inputs["url"])
    return "Невідомий інструмент."


async def run_agent(user_id: int, messages: list) -> str:
    """Agentic loop: runs until stop_reason == 'end_turn'."""
    while True:
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
            return "(порожня відповідь)"

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = execute_tool(block.name, block.input, user_id)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    })
            messages.append({"role": "user", "content": tool_results})
        else:
            return "(агент завершив роботу)"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conversation_history[user.id] = []
    await update.message.reply_text(
        f"Привіт, {user.first_name}! 👋\n"
        "Я бізнес-асистент на базі Claude з інструментами:\n\n"
        "🧮 Розрахунки\n📝 Нотатки\n🕐 Дата і час\n🌐 Читання сайтів\n🖼 Аналіз фото\n\n"
        "Команди: /start · /clear · /notes"
    )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conversation_history[update.effective_user.id] = []
    await update.message.reply_text("✅ Історію очищено.")


async def notes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = tool_list_notes(user_id)
    await update.message.reply_text(text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text or ""

    if user.id not in conversation_history:
        conversation_history[user.id] = []

    conversation_history[user.id].append({"role": "user", "content": text})
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        reply = await run_agent(user.id, list(conversation_history[user.id]))
        conversation_history[user.id].append({"role": "assistant", "content": reply})
        if len(conversation_history[user.id]) > 40:
            conversation_history[user.id] = conversation_history[user.id][-40:]
        await update.message.reply_text(reply)
    except Exception as e:
        logger.error(f"Agent error: {e}")
        await update.message.reply_text("⚠️ Помилка агента. Спробуй ще раз.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    caption = update.message.caption or "Що зображено на фото? Опиши детально."

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image_bytes = bytes(await file.download_as_bytearray())
    import base64
    b64 = base64.standard_b64encode(image_bytes).decode()

    try:
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text": caption}
                ]
            }]
        )
        await update.message.reply_text(response.content[0].text)
    except Exception as e:
        logger.error(f"Vision error: {e}")
        await update.message.reply_text("⚠️ Не вдалося проаналізувати фото.")


def main():
    logger.info("Agent bot started with tools")
    app = ApplicationBuilder().token(TG_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("notes", notes_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
