# Queen AI Trader — MVP

نسخة أولية لوكيل تداول خاص بالذهب XAUUSD.

## ماذا تفعل هذه النسخة؟
- تستقبل تنبيهات TradingView عبر Webhook.
- تتحقق من كلمة مرور التنبيه.
- تحسب Queen Score من 100.
- ترفض الإشارات الضعيفة.
- ترسل الإشارات المقبولة إلى Telegram.
- تحفظ كل إشارة في سجل JSONL.
- تضع حدودًا يومية للمخاطرة وعدد الصفقات.

## مهم
هذه النسخة لا تنفذ صفقات تلقائيًا، ولا تضمن الربح. هي نظام تحليل وتنبيه ومراقبة مخاطر.

## التشغيل المحلي
1. ثبتي Python 3.11 أو أحدث.
2. انسخي `.env.example` إلى `.env`.
3. ضعي القيم المطلوبة.
4. نفذي:
   pip install -r requirements.txt
   uvicorn app.main:app --reload --port 8000

## ربط TradingView
استخدمي رابط:
https://YOUR-DOMAIN/webhook/tradingview

وضعي رسالة التنبيه بصيغة JSON مطابقة للنموذج الموجود في:
tradingview_alert_example.json

## الحقول الأساسية
- symbol
- timeframe
- side
- entry
- stop_loss
- take_profit_1
- take_profit_2
- take_profit_3
- liquidity_sweep
- mss
- fvg
- order_block
- session
- rr
- secret

## الخطوة التالية
بعد نجاح الـ MVP نضيف:
- تحليل متعدد الفريمات.
- فلتر الأخبار.
- SMT بين الذهب والفضة وDXY.
- لوحة تحكم.
- سجل أداء وإحصاءات.
- Agent لغوي يشرح سبب الصفقة.
