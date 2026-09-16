from pathlib import Path

p = Path("main.py")
s = p.read_text(encoding="utf-8")

# Restore bidi import if absent.
if "from bidi.algorithm import get_display" not in s:
    marker = "import websocket"
    if marker in s:
        s = s.replace(
            marker,
            marker + "\nimport arabic_reshaper\nfrom bidi.algorithm import get_display",
            1,
        )

start = s.find("def ar(")
if start == -1:
    raise SystemExit("لم أجد def ar في main.py")

next_marker = s.find("\n\n", start)
while next_marker != -1:
    tail = s[next_marker + 2:].lstrip()
    if tail.startswith("#") or tail.startswith("class "):
        break
    next_marker = s.find("\n\n", next_marker + 2)

if next_marker == -1:
    raise SystemExit("تعذر تحديد نهاية دالة ar")

new_func = '''def ar(value: str) -> str:
    """Shape Arabic into visual glyph order for the SDL2 renderer."""
    if not value:
        return value

    if not re.search(r"[\\u0600-\\u06ff]", value):
        return value

    try:
        shaped = arabic_reshaper.reshape(value)
        return get_display(shaped)
    except Exception:
        return value
'''

s = s[:start] + new_func + s[next_marker:]

# Critical: transformed visual-order strings must NOT be processed RTL again.
s = s.replace(
    'kwargs.setdefault("base_direction", "rtl")',
    'kwargs.setdefault("base_direction", "ltr")'
)

p.write_text(s, encoding="utf-8")
print("تم تعديل main.py مع الحفاظ على UTF-8.")
