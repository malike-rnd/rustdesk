#!/usr/bin/env python3
"""Накладывает бренд (branding/brand.conf) на дерево исходников перед сборкой.

    python3 branding/apply.py            # применить (так делает CI после checkout)
    python3 branding/apply.py --dry-run  # только проверить, что все места найдены (ничего не пишет)

Правит в т.ч. submodule libs/hbb_common (сервер, ключ, APP_NAME) — поэтому сам submodule остаётся
upstream rustdesk/hbb_common, а бренд живёт только здесь. Скрипт идемпотентный (повторный запуск
ничего не ломает) и падает с ошибкой, если какой-то шаблон не найден: после обновления от upstream
лучше упасть, чем молча собрать «RustDesk» с чужим сервером.
Только стандартная библиотека Python 3; работает на Linux/macOS/Windows раннерах.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.join(ROOT, "branding", "brand.conf")
DRY = "--dry-run" in sys.argv
errors = []
changed = []


def load_conf():
    conf = {}
    with open(CONF, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                sys.exit(f"brand.conf:{n}: ожидается КЛЮЧ=значение")
            k, v = line.split("=", 1)
            conf[k.strip()] = v.strip()
    for k in list(conf):
        env = os.environ.get("BRAND_" + k, "").strip()
        if env:
            conf[k] = env
    return conf


C = load_conf()
APP = C.get("APP_NAME", "")
SERVER = C.get("RENDEZVOUS_SERVER", "")
KEY = C.get("RS_PUB_KEY", "")
HOME = C.get("HOMEPAGE_URL", "")
PRIVACY = C.get("PRIVACY_URL", "") or HOME
SOURCE = C.get("SOURCE_URL", "")
DOCS = C.get("DOCS_URL", "")

# Значения подставляются в Rust/Kotlin/Dart/XML/plist — допускаем только безопасные символы.
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,40}", APP):
    sys.exit(f"APP_NAME={APP!r}: допустимы латиница, цифры, пробел, . _ - (до 41 символа)")
if not re.fullmatch(r"[A-Za-z0-9.-]+(:\d+)?", SERVER):
    sys.exit(f"RENDEZVOUS_SERVER={SERVER!r}: ожидается хост[:порт]")
if not re.fullmatch(r"[A-Za-z0-9+/]{43}=", KEY):
    sys.exit("RS_PUB_KEY: ожидается base64 ed25519-ключ (44 символа)")
for name, url in (("HOMEPAGE_URL", HOME), ("PRIVACY_URL", PRIVACY), ("SOURCE_URL", SOURCE)):
    if not re.fullmatch(r"https?://[A-Za-z0-9._~:/?#@!$&()*+,;=%-]+", url or "") or "'" in url:
        sys.exit(f"{name}={url!r}: ожидается http(s)-URL")
if DOCS and not re.fullmatch(r"https?://[A-Za-z0-9._~:/?#@!$&()*+,;=%-]+", DOCS):
    sys.exit(f"DOCS_URL={DOCS!r}: ожидается http(s)-URL")


def short(url):
    return re.sub(r"^https?://(www\.)?", "", url).rstrip("/")


class File:
    def __init__(self, rel):
        self.rel = rel
        self.path = os.path.join(ROOT, *rel.split("/"))
        if not os.path.isfile(self.path):
            errors.append(f"{rel}: файл не найден")
            self.text = None
            return
        with open(self.path, encoding="utf-8", newline="") as f:
            self.text = self.orig = f.read()

    def sub(self, pattern, repl, count=1, flags=re.M, done=None):
        """Регулярка: должна найтись ровно count раз (None — хотя бы раз).
        done — строка-признак «уже применено» (для повторного запуска), если шаблон содержит старое значение."""
        if self.text is None:
            return self
        n = len(re.findall(pattern, self.text, flags))
        if n == 0 and done is not None and done in self.text:
            return self
        if n == 0 or (count is not None and n != count):
            errors.append(f"{self.rel}: шаблон /{pattern}/ найден {n} раз, ожидалось {count or '>=1'}")
            return self
        self.text = re.sub(pattern, repl, self.text, flags=flags)
        return self

    def replace(self, old, new, count=1):
        """Строка: заменить первые count вхождений (None — все); если old уже нет, а new есть — уже применено."""
        if self.text is None or old == new:
            return self
        n = self.text.count(old)
        if n >= (count or 1):
            self.text = self.text.replace(old, new, -1 if count is None else count)
        elif n == 0 and new in self.text:
            pass
        else:
            errors.append(f"{self.rel}: не найдено {old!r} (нужно {count}, есть {n})")
        return self

    def save(self):
        if self.text is not None and self.text != self.orig:
            changed.append(self.rel)
            if not DRY:
                with open(self.path, "w", encoding="utf-8", newline="") as f:
                    f.write(self.text)


def q(v):
    """Замена для re.sub — экранируем обратные слэши."""
    return v.replace("\\", "\\\\")


# --- 1. Ядро: сервер, ключ, имя приложения (submodule hbb_common) ----------------------------------
File("libs/hbb_common/src/config.rs") \
    .sub(r'(pub static ref PROD_RENDEZVOUS_SERVER: RwLock<String> = RwLock::new\()"[^"]*"', rf'\1"{q(SERVER)}"') \
    .sub(r'(pub static ref APP_NAME: RwLock<String> = RwLock::new\()"[^"]*"', rf'\1"{q(APP)}"') \
    .sub(r'(pub const RENDEZVOUS_SERVERS: &\[&str\] = &\[)[^\]]*\]', rf'\1"{q(SERVER)}"]') \
    .sub(r'(pub const RS_PUB_KEY: &str = )"[^"]*"', rf'\1"{q(KEY)}"') \
    .save()

# --- 2. Свойства exe (Windows) ---------------------------------------------------------------------
for rel in ("Cargo.toml", "libs/portable/Cargo.toml"):
    File(rel).sub(r'^((?:description|ProductName|FileDescription) = ")RustDesk\b', rf"\1{q(APP)}", count=3,
                  done=f'ProductName = "{APP}"').save()
File("flutter/windows/runner/Runner.rc") \
    .sub(r'(VALUE "(?:FileDescription|ProductName)", ")RustDesk\b', rf"\1{q(APP)}", count=2,
         done=f'"ProductName", "{APP}"').save()

# --- 3. Android ------------------------------------------------------------------------------------
File("flutter/android/app/src/main/AndroidManifest.xml") \
    .sub(r'(<application\b[^>]*?android:label=")[^"]*"', rf'\1{q(APP)}"', flags=re.S) \
    .sub(r'(android:name="\.InputService"[^>]*?android:label=")[^"]*"', rf'\1{q(APP)} Input"', flags=re.S) \
    .save()
File("flutter/android/app/src/main/res/values/strings.xml") \
    .sub(r'(<string name="app_name">)[^<]*<', rf"\1{q(APP)}<") \
    .replace("RustDesk", APP, count=None) \
    .save()
File("flutter/android/app/src/main/kotlin/com/carriez/flutter_hbb/MainService.kt") \
    .sub(r'(const val DEFAULT_NOTIFY_TITLE = ")[^"]*"', rf'\1{q(APP)}"') \
    .sub(r'(val channelName = ")RustDesk( Service")', rf"\1{q(APP)}\2", done=f'"{APP} Service"') \
    .sub(r'(description = ")RustDesk( Service Channel")', rf"\1{q(APP)}\2", done=f'"{APP} Service Channel"') \
    .save()
File("flutter/android/app/src/main/kotlin/com/carriez/flutter_hbb/BootReceiver.kt") \
    .sub(r'"RustDesk is Open"', f'"{q(APP)} is Open"', done=f'"{APP} is Open"') \
    .save()

# --- 4. macOS / iOS (имя .app и бинарника не меняем — только отображаемое имя) --------------------------
File("flutter/macos/Runner/Info.plist") \
    .sub(r"(<key>CFBundleName</key>\s*<string>)[^<]*(</string>)", rf"\g<1>{q(APP)}\2").save()
File("flutter/ios/Runner/Info.plist") \
    .sub(r"(<key>CFBundle(?:Display)?Name</key>\s*<string>)[^<]*(</string>)", rf"\g<1>{q(APP)}\2", count=2).save()

# --- 5. Linux: ярлыки, служба, flatpak --------------------------------------------------------------
for rel in ("res/rustdesk.desktop", "res/rustdesk-link.desktop"):
    File(rel).sub(r"^Name=(?!Open a New Window).*$", f"Name={q(APP)}").save()
File("res/rustdesk.service").sub(r"^Description=.*$", f"Description={q(APP)}").save()
File("flatpak/com.rustdesk.RustDesk.metainfo.xml") \
    .sub(r"(</launchable>.*?<name>)[^<]*(</name>)", rf"\g<1>{q(APP)}\2", flags=re.S).save()

# --- 6. Ссылки в интерфейсе Flutter (помощь, сайт, privacy, исходники) --------------------------------
File("flutter/lib/common.dart") \
    .replace("launchUrl(Uri.parse('https://rustdesk.com'));", f"launchUrl(Uri.parse('{SOURCE}'));") \
    .save()
File("flutter/lib/desktop/pages/desktop_setting_page.dart") \
    .replace("launchUrlString('https://rustdesk.com/privacy.html');", f"launchUrlString('{PRIVACY}');") \
    .replace("launchUrlString('https://rustdesk.com');", f"launchUrlString('{HOME}');") \
    .save()
File("flutter/lib/desktop/pages/install_page.dart") \
    .replace("'https://rustdesk.com/privacy.html'", f"'{PRIVACY}'", count=2) \
    .save()
File("flutter/lib/mobile/pages/settings_page.dart") \
    .sub(r"^const url = '[^']*';", f"const url = '{SOURCE}';") \
    .replace("Text('rustdesk.com',", f"Text('{short(SOURCE)}',") \
    .replace("launchUrlString('https://rustdesk.com/privacy.html')", f"launchUrlString('{PRIVACY}')") \
    .sub(r"^(\s+)const url = 'https://rustdesk.com/';", rf"\1const url = '{HOME}';", done=f"const url = '{HOME}';") \
    .replace("Text('rustdesk.com',", f"Text('{short(HOME)}',") \
    .save()
if DOCS:
    File("flutter/lib/desktop/pages/desktop_home_page.dart") \
        .sub(r"'https://rustdesk\.com/docs/[^']*'", f"'{DOCS}'", count=None, done=f"'{DOCS}'").save()

# --- 7. Ссылки в Sciter-интерфейсе (сборки *-sciter) ---------------------------------------------------
File("src/ui/index.tis") \
    .replace("url='https://rustdesk.com/privacy.html'", f"url='{PRIVACY}'") \
    .replace("url='https://rustdesk.com'", f"url='{HOME}'") \
    .sub(r'(event click \$\(#powered-by\) \{\s*handler\.open_url\(")[^"]*"', rf'\1{SOURCE}"', flags=re.S) \
    .save()
File("src/ui/install.tis") \
    .replace('view.open_url("http://rustdesk.com/privacy");', f'view.open_url("{PRIVACY}");') \
    .save()

# ------------------------------------------------------------------------------------------------------
if errors:
    print("branding/apply.py: ОШИБКА — шаблоны не найдены (upstream изменил файлы?):", file=sys.stderr)
    for e in errors:
        print("  - " + e, file=sys.stderr)
    sys.exit(1)

print(f"branding: APP_NAME={APP!r}, server={SERVER}, key={KEY[:6]}…; "
      f"{'проверено (dry-run)' if DRY else 'изменено'} файлов: {len(changed)}")
for c in changed:
    print("  " + c)
gh_env = os.environ.get("GITHUB_ENV")
if gh_env and not DRY:
    with open(gh_env, "a", encoding="utf-8") as f:
        f.write(f"BRAND_APP_NAME={APP}\n")
