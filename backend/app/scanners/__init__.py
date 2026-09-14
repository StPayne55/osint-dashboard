from __future__ import annotations

from app.scanners.base import Scanner
from app.scanners.dorks_scan import DorkScanner
from app.scanners.email_intel import EmailIntelScanner
from app.scanners.gravatar_scan import GravatarScanner
from app.scanners.harvester_scan import HarvesterScanner
from app.scanners.hibp_scan import HibpScanner
from app.scanners.holehe_scan import HoleheScanner
from app.scanners.maigret_scan import MaigretScanner
from app.scanners.numverify_scan import NumverifyScanner
from app.scanners.pdl_scan import PdlScanner
from app.scanners.phone_scan import PhoneScanner
from app.scanners.sherlock_scan import SherlockScanner
from app.scanners.socialscan_scan import SocialscanScanner
from app.scanners.spiderfoot_scan import SpiderFootScanner
from app.scanners.trestle_scan import TrestleReversePhoneScanner
from app.scanners.twilio_scan import TwilioLookupScanner
from app.scanners.whitepages_scan import WhitepagesProScanner
from app.scanners.usernames import UsernameCandidateScanner

# AbstractPhoneScanner stays in abstract_phone_scan.py but is not registered.
# It is disabled pending an AbstractAPI key so Catalog and live scans do not
# show a skipped-without-key module.


def all_scanners() -> list[Scanner]:
    return [
        UsernameCandidateScanner(),
        EmailIntelScanner(),
        GravatarScanner(),
        HoleheScanner(),
        SocialscanScanner(),
        SherlockScanner(),
        MaigretScanner(),
        SpiderFootScanner(),
        PhoneScanner(),
        HarvesterScanner(),
        DorkScanner(),
        HibpScanner(),
        PdlScanner(),
        NumverifyScanner(),
        TwilioLookupScanner(),
        WhitepagesProScanner(),
        TrestleReversePhoneScanner(),
    ]
