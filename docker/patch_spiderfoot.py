#!/usr/bin/env python3
"""Patch SpiderFoot v4.0 so Account Finder works with current WhatsMyName data.

v4.0 still fetches the retired web_accounts_list.json (check_uri / category).
WhatsMyName now publishes wmn-data.json (uri_check / cat / e_code).
Also drops breach / dark-web modules so a later -u usecase cannot enable them.

A second pass wires Account Finder into docker/accounts_tune.py so the
716-site distrust sweep can be skipped and the site list capped. Without
that, a cold sf.py on Render Starter dies during checkSites(randuser) and
salvages only the seed USERNAME event.
"""
from __future__ import annotations

import shutil
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


OLD_FETCH_BLOCK = '''        content = self.sf.cacheGet("sfaccountsv2", 48)
        if content is None:
            url = "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/wmn-data.json"
            data = self.sf.fetchUrl(url, useragent="SpiderFoot")

            if data['content'] is None:
                self.error(f"Unable to fetch {url}")
                self.errorState = True
                return

            content = data['content']
            self.sf.cachePut("sfaccountsv2", content)

        try:
            self.sites = [site for site in json.loads(content)['sites'] if site.get('valid', True) is not False]
        except Exception as e:
            self.error(f"Unable to parse social media accounts list: {e}")
            self.errorState = True
            return
'''

NEW_FETCH_BLOCK = '''        content = self.sf.cacheGet("sfaccountsv2", 48)
        if content is None:
            try:
                from accounts_tune import bundled_wmn_content
                content = bundled_wmn_content()
            except Exception:
                content = None
            if content is None:
                url = "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/wmn-data.json"
                data = self.sf.fetchUrl(url, useragent="SpiderFoot")

                if data['content'] is None:
                    self.error(f"Unable to fetch {url}")
                    self.errorState = True
                    return

                content = data['content']

            self.sf.cachePut("sfaccountsv2", content)

        try:
            from accounts_tune import load_sites
            self.sites = load_sites(content)
        except Exception as e:
            self.error(f"Unable to parse social media accounts list: {e}")
            self.errorState = True
            return
'''

OLD_DISTRUST_BLOCK = '''        # If being called for the first time, let's see how trusted the
        # sites are by attempting to fetch a garbage user.
        if not self.distrustedChecked:
            # Check if a state cache exists first, to not have to do this all the time
            content = self.sf.cacheGet("sfaccounts_state_v2", 72)
            if content:
                if content != "None":  # "None" is written to the cached file when no sites are distrusted
                    delsites = list()
                    for line in content.split("\\n"):
                        if line == '':
                            continue
                        delsites.append(line)
                    self.sites = [d for d in self.sites if d['name'] not in delsites]
            else:
                randpool = 'abcdefghijklmnopqrstuvwxyz1234567890'
                randuser = ''.join([random.SystemRandom().choice(randpool) for x in range(10)])
                res = self.checkSites(randuser)
                if res:
                    delsites = list()
                    for site in res:
                        sitename = site.split(" (Category:")[0]
                        self.debug(f"Distrusting {sitename}")
                        delsites.append(sitename)
                    self.sites = [d for d in self.sites if d['name'] not in delsites]
                else:
                    # The caching code needs *some* content
                    delsites = "None"
                self.sf.cachePut("sfaccounts_state_v2", delsites)

            self.distrustedChecked = True
'''

NEW_DISTRUST_BLOCK = '''        # If being called for the first time, let's see how trusted the
        # sites are by attempting to fetch a garbage user.
        # OSINT Desk: skip the 715-site sweep unless SPIDERFOOT_SKIP_DISTRUST=0.
        # WMN e_code / e_string already reject sites that match a random user.
        if not self.distrustedChecked:
            try:
                from accounts_tune import should_skip_distrust
                skip_distrust = should_skip_distrust()
            except Exception:
                skip_distrust = True
            if skip_distrust:
                self.debug("Skipping WhatsMyName distrust sweep (SPIDERFOOT_SKIP_DISTRUST)")
            else:
                content = self.sf.cacheGet("sfaccounts_state_v2", 72)
                if content:
                    if content != "None": # "None" is written to the cached file when no sites are distrusted
                        delsites = list()
                        for line in content.split("\\n"):
                            if line == '':
                                continue
                            delsites.append(line)
                        self.sites = [d for d in self.sites if d['name'] not in delsites]
                else:
                    randpool = 'abcdefghijklmnopqrstuvwxyz1234567890'
                    randuser = ''.join([random.SystemRandom().choice(randpool) for x in range(10)])
                    res = self.checkSites(randuser)
                    if res:
                        delsites = list()
                        for site in res:
                            sitename = site.split(" (Category:")[0]
                            self.debug(f"Distrusting {sitename}")
                            delsites.append(sitename)
                        self.sites = [d for d in self.sites if d['name'] not in delsites]
                    else:
                        # The caching code needs *some* content
                        delsites = "None"
                    self.sf.cachePut("sfaccounts_state_v2", delsites)

            self.distrustedChecked = True
'''


def _replace_once(text: str, old: str, new: str, path: Path) -> str:
    if old not in text:
        raise SystemExit(f"patch marker not found in {path}: {old[:80]!r}")
    return text.replace(old, new, 1)


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
        (OLD_FETCH_BLOCK, NEW_FETCH_BLOCK),
        (OLD_DISTRUST_BLOCK, NEW_DISTRUST_BLOCK),
    )
    for old, new in replacements:
        text = _replace_once(text, old, new, path)
    path.write_text(text, encoding="utf-8")
    print(f"patched {path}")


def install_tune_module(home: Path) -> None:
    src = Path(__file__).resolve().parent / "accounts_tune.py"
    if not src.is_file():
        raise SystemExit(f"accounts_tune.py missing next to patch script: {src}")
    dest = home / "accounts_tune.py"
    shutil.copy2(src, dest)
    print(f"installed {dest}")
    priority = Path(__file__).resolve().parent / "wmn-priority.json"
    if priority.is_file():
        data_dir = home / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        dest_priority = data_dir / "wmn-priority.json"
        shutil.copy2(priority, dest_priority)
        print(f"installed {dest_priority}")


def bake_cache(home: Path) -> None:
    # Imported after copy so the bake uses the installed module.
    sys.path.insert(0, str(home))
    from accounts_tune import bake_spiderfoot_cache, bundled_wmn_content

    cache_dir = home / "cache"
    written = bake_spiderfoot_cache(cache_dir, wmn_content=bundled_wmn_content())
    for path in written:
        print(f"baked cache {path.name}")


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
    install_tune_module(home)
    patch_accounts(home)
    bake_cache(home)
    drop_blocked(home)


if __name__ == "__main__":
    main()
