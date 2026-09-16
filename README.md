# فـهـد — FAHD Smart Remote

فـهـد هو تطبيق ريموت محلي للهاتف مبني باستخدام Python وKivy، ومخصص حاليًا لأجهزة LG Smart TV التي تستخدم webOS وبروتوكول SSAP.

التطبيق لا يحتاج إلى حساب أو خدمة سحابية. الهاتف والتلفزيون يتواصلان مباشرة داخل الشبكة المحلية.

## حالة الدعم

البروتوكول المنفذ حاليًا:

- LG webOS SSAP عبر WebSocket.
- قناة Network Input الخاصة بـ webOS للـ Pointer والأزرار المدعومة.
- Pairing وclient-key.
- إعادة الاتصال.
- التحكم بالصوت.
- القنوات عند توفرها.
- التطبيقات عند توفرها.
- Media controls عند توفر قناة الإدخال.
- Text Input باستخدام webOS IME.
- Pointer حقيقي باستخدام `getPointerInputSocket`.

لا يدعي المشروع دعم:

- Samsung.
- Sony.
- Roku.
- Fire TV.
- Android TV كبروتوكول عام.
- التحكم العام عبر Bluetooth.

إضافة اسم شركة إلى Discovery لا تكفي لاعتبارها مدعومة؛ كل منصة تحتاج Controller حقيقي مستقل.

## متطلبات التطوير

يوصى باستخدام Python 3.11 أو Python 3.12 على جهاز التطوير.

بناء Android باستخدام Buildozer يعمل بصورة أساسية على Linux. يمكن على Windows استخدام WSL2.

## إنشاء Virtual Environment

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt