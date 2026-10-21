# برنامج حسابات البضاعة (المرحلة 1: مخازن + موردين + عملاء | المرحلة 2: الخزينة | المرحلة 3: المشتريات | المرحلة 4: المبيعات | المرحلة 5: التقارير)

> التوثيق الكامل (الهيكل، قاعدة البيانات، القواعد، تدفقات الفواتير والخزينة، وإزاي تعدّل): **[DOCS.md](DOCS.md)**

## التشغيل
```
cd stock_project
python3 -m venv venv && source venv/bin/activate     # أول مرة بس
pip install -r requirements.txt        # PySide6 + openpyxl (تصدير Excel)
python main.py
```

## قبل أول تشغيل على بياناتك الحقيقية (مهم)
البرنامج هيرحّل `~/HesabatStock/stock.db` القديم تلقائياً أول مرة. جرّب الترحيل الأول على نسخة:
```
python3 tools/test_migration.py ~/HesabatStock/stock.db
```
الأداة بتشتغل على نسخة مؤقتة وبتطبع تقرير مطابقة (عدد الأصناف، مجموع الأرصدة، القيم، المبيعات، الربح). اعتمد التشغيل الحقيقي بس لو النتيجة "متطابق ✔".
وكمان البرنامج نفسه بياخد نسخة احتياطية في `~/HesabatStock/backups/` ويتراجع تلقائياً لو الأرقام مش متطابقة.

## الاختبارات
```
cd tests
python3 -m unittest test_core test_treasury test_invoices test_sales test_reports test_search test_packaging smoke_ui_stub -v
```
(أو `pytest tests` لو pytest متثبت)

## ترقية قاعدة البيانات
أول تشغيل بعد التحديث بيرقّي القاعدة خطوة خطوة لآخر نسخة (3 = جداول الفواتير)، وكل خطوة بنسخة احتياطية قبلها في `~/HesabatStock/backups/` (`stock_before_v3_...db`). بياناتك الحالية مبتتلمسش.

## الهيكل
```
main.py                 نقطة التشغيل
hesabat/db/             الاتصال + transaction (tx) + الهيكل + الترحيل
hesabat/logic/          منطق العمل (كل الحسابات والتحقق) - مفيش PySide6 هنا
hesabat/ui/             الشاشات - بتنادي دوال logic بس، مفيش SQL
tests/  tools/
```

## قواعد الأرقام
المبالغ بالقروش (int) والكميات بالألف (int)، مفيش float في أي حساب.

## بناء exe لويندوز
التفاصيل في [DOCS.md](DOCS.md) (قسم 15). باختصار: ارفع المشروع على GitHub (Private) وشغّل **Build Windows exe** من تبويب Actions، أو على جهاز ويندوز شغّل `build_windows.bat`. دليل العميل: [CUSTOMER_GUIDE_AR.md](CUSTOMER_GUIDE_AR.md).
