#!/usr/bin/env python3
"""Patch SpiderFoot v4.0 so Account Finder works with current WhatsMyName data.

v4.0 still fetches the retired web_accounts_list.json (check_uri / category).
WhatsMyName now publishes wmn-data.json (uri_check / cat / e_code).
Also drops breach / dark-web modules so a later -u usecase cannot enable them.
"""
from __future__ import annotations

import sys
from pathlib import Path

BLOCKED_MODULES = (
    "sfp_haveibeenpwned.py",
    "sfp_dehashed.py",
    "sfp_ahmia.py",
    "sfp_onioncity.py",
    "sfp_onionsearchengine.py",
    "sfp_torch.py",
    "sfp_leakix.py",
    "sfp_intelx.py",
    "sfp_psbdmp.py",
    "sfp_pastebin.py",
    "sfp_sociallinks.py",
    "sfp_breachdirectory.py",
    "sfp_leaklookup.py",
)

OLD_URL = (
    "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/master/web_accounts_list.json"
)
NEW_URL = "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/wmn-data.json"

OLD_SITES = (
    "self.sites = [site for site in json.loads(content)['sites'] if site['valid']]"
)
NEW_SITES = (
    "self.sites = [site for site in json.loads(content)['sites'] "
    "if site.get('valid', True) is not False]"
)

OLD_CHECK = '''        if 'check_uri' not in site:
            return

        url = site['check_uri'].format(account=name)
        if 'pretty_uri' in site:
            ret_url = site['pretty_uri'].format(account=name)
        else:
            ret_url = url
        retname = f"{site['name']} (Category: {site['category']})\\n<SFURL>{ret_url}</SFURL>"
'''

NEW_CHECK = '''        url_tmpl = site.get('uri_check') or site.get('check_uri')
        if not url_tmpl:
            return

        url = url_tmpl.format(account=name)
        pretty = site.get('uri_pretty') or site.get('pretty_uri')
        ret_url = pretty.format(account=name) if pretty else url
        category = site.get('cat') or site.get('category') or 'unknown'
        retname = f"{site['name']} (Category: {category})\\n<SFURL>{ret_url}</SFURL>"
'''

OLD_CODE = "        if res['code'] != site.get('account_existence_code'):"
NEW_CODE = (
    "        exist_code = site.get('account_existence_code') or site.get('e_code')\n"
    "        if exist_code is not None and str(res['code']) != str(exist_code):"
)

OLD_STRING = "        if site.get('account_existence_string') not in res['content']:"
NEW_STRING = (
    "        exist_string = site.get('account_existence_string') or site.get('e_string')\n"
    "        if exist_string and exist_string not in res['content']:"
)


def patch_accounts(home: Path) -> None:
    path = home / "modules" / "sfp_accounts.py"
    text = path.read_text(encoding="utf-8")
    replacements = (
        (OLD_URL, NEW_URL),
        ('self.sf.cacheGet("sfaccounts", 48)', 'self.sf.cacheGet("sfaccountsv2", 48)'),
        ('self.sf.cachePut("sfaccounts", content)', 'self.sf.cachePut("sfaccountsv2", content)'),
        (OLD_SITES, NEW_SITES),
        (OLD_CHECK, NEW_CHECK),
        (OLD_CODE, NEW_CODE),
        (OLD_STRING, NEW_STRING),
    )
    for old, new in replacements:
        if old not in text:
            raise SystemExit(f"patch marker not found in {path}: {old[:80]!r}")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    print(f"patched {path}")


def drop_blocked(home: Path) -> None:
    modules = home / "modules"
    for name in BLOCKED_MODULES:
        path = modules / name
        if path.exists():
            path.unlink()
            print(f"removed {path.name}")


def main() -> None:
    home = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/spiderfoot")
    if not (home / "sf.py").is_file():
        raise SystemExit(f"sf.py missing under {home}")
    patch_accounts(home)
    drop_blocked(home)


if __name__ == "__main__":
    main()
