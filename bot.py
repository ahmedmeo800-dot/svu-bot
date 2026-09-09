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
        r1 = session.get(SITE_URL, timeout=15)
        soup = BeautifulSoup(r1.text, "html.parser")

        payload = {}
        for inp in soup.find_all("input"):
            name = inp.get("name")
            val = inp.get("value", "")
            if name:
                payload[name] = val

        txt_name = None
        for inp in soup.find_all("input", {"type": "text"}):
            n = inp.get("name", "")
            if "txt" in n.lower() or "national" in n.lower() or "id" in n.lower():
                txt_name = n
                break
        if not txt_name:
            for inp in soup.find_all("input", {"type": "text"}):
                txt_name = inp.get("name")
                break
        if not txt_name:
            txt_name = "txtNationalId"

        payload[txt_name] = national_id

        submit_name = None
        for inp in soup.find_all(["input", "button"], {"type": "submit"}):
            n = inp.get("name")
            if n:
                submit_name = n
                payload[n] = inp.get("value", "استعلام")
                break
        if not submit_name:
            payload["btnSearch"] = "استعلام"

        r2 = session.post(SITE_URL, data=payload, timeout=20)
        res_soup = BeautifulSoup(r2.text, "html.parser")

        # استخراج اسم الطالب والبيانات من الصفحة
        student_name = "غير معروف"
        tables = res_soup.find_all("table")

        unpaid_items = []
        total_due = 0.0

        # تحليل الجداول لاستخراج البنود والمبالغ
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cols = row.find_all(["td", "th"])
                col_texts = [
                    c.get_text(strip=True)
                    for c in cols
                    if c.get_text(strip=True)
                ]

                if not col_texts:
                    continue

                full_row_str = " | ".join(col_texts)

                # محاولة التقاط اسم الطالب إذا وجد في الجداول
                for text in col_texts:
                    if (
                        any(
                            name_keyword in text
                            for name_keyword in [
                                "الاسم",
                                "طالب",
                                "السيد",
                                "الادارة",
                            ]
                        )
                        and len(text) > 5
                        and student_name == "غير معروف"
                    ):
                        student_name = text

                # البحث عن الأرقام المالية في الأعمدة والتحقق مما إذا لم تُسدد
                for i, text in enumerate(col_texts):
                    # تنظيف النص للبحث عن أرقام مالية (مثلاً تحتوي على أرقام وعلامة عشرية)
                    clean_num_str = re.sub(r"[^\d.]", "", text)
                    if clean_num_str and len(clean_num_str) > 0:
                        try:
                            val = float(clean_num_str)
                            # إذا كانت القيمة أكبر من الصفر وليست سنة أو رقم قومي
                            if 0 < val < 500000 and len(clean_num_str) < 7:
                                # التحقق من حالة السداد في السطر (مثل كلمة "غير مسدد", "مستحق", أو اسم بند مصروفات)
                                row_lower = full_row_str.lower()
                                if (
                                    "تم السداد" not in row_lower
                                    and "مسدد" not in row_lower
                                    and "خالص" not in row_lower
                                ):
                                    # استخراج اسم البند (النص الموجود في أول عمود عادة)
                                    item_name = (
                                        col_texts[0]
                                        if len(col_texts[0]) > 2
                                        else "مصروفات دراسية/إدارية"
                                    )
                                    if item_name not in [
                                        x["name"] for x in unpaid_items
                                    ]:
                                        unpaid_items.append(
                                            {"name": item_name, "amount": val}
                                        )
                                        total_due += val
                                        break
                        except ValueError:
                            pass

        # إذا لم يتم تحليل بنود مالية بذكاء، نعرض النصوص الخام للجدول بشكل منظم
        raw_text_summary = []
        for table in tables:
            for row in table.find_all("tr"):
                t = row.get_text(separator=" - ", strip=True)
                if (
                    t
                    and len(t) > 5
                    and "ReportViewer" not in t
                    and "javascript" not in t
                ):
                    raw_text_summary.append(t)

        return {
            "student_name": student_name,
            "unpaid_items": unpaid_items,
            "total_due": total_due,
            "raw_text": "\n".join(raw_text_summary[:15]),
        }

    except Exception as e:
        return {"error": str(e)}


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    user = update.effective_user

    if not user_input.isdigit() or len(user_input) != 14:
        await update.message.reply_text(
            "يرجى إرسال الرقم القومي المكون من 14 رقماً بشكل صحيح للاستعلام."
        )
        return

    await update.message.reply_text("جاري فحص المصروفات من سيرفر الجامعة...")

    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(
        None, fetch_expenses_from_site, user_input
    )

    if "error" in data:
        result_msg = f"حدث خطأ أثناء الاتصال بالنظام: {data['error']}"
        channel_msg = f"⚠️ خطأ استعلام للرقم `{user_input}` من المستخدم {user.full_name}"
    else:
        s_name = data.get("student_name", "غير متوفر")
        items = data.get("unpaid_items", [])
        total = data.get("total_due", 0.0)

        # بناء شكل الرسالة المطلوبة بشكل منظم
        items_list_str = ""
        if items:
            for idx, item in enumerate(items, 1):
                items_list_str += (
                    f"   {idx}. {item['name']} : {item['amount']} جنية\n"
                )
        else:
            items_list_str = (
                "   - لا توجد تفصيلات مفردة، راجع النص أدناه أو النظام.\n"
            )

        formatted_result = (
            f"👤 **الاسم:** {s_name}\n"
            f"🆔 **الرقم القومي:** `{user_input}`\n\n"
            f"📌 **المصروفات التي لم يتم تسديدها:**\n{items_list_str}\n"
            f"💰 **إجمالي المطلوب تسديده:** *{total} جنية*\n\n"
            f"📋 **بيانات إضافية من النظام:**\n{data.get('raw_text', '')}"
        )

        result_msg = formatted_result

        # الرسالة التي ستصل إليك في قناتك الخاصة بشكل سري ومنظم
        channel_msg = (
            f"📥 **استعلام جديد (مفصل):**\n"
            f"👤 المستخدم بالبوت: {user.full_name} (@{user.username or 'بدون'})\n"
            f"🆔 آيدي المستخدم: `{user.id}`\n\n"
            f"{formatted_result}"
        )

    # إرسال التقرير إلى قناتك الخاصة
    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID, text=channel_msg, parse_mode="Markdown"
        )
    except Exception as err:
        print(f"Error logging to channel: {err}")

    # إرسال النتيجة للطالب في الشات
    await update.message.reply_text(result_msg, parse_mode="Markdown")


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
