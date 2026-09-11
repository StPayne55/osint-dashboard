from __future__ import annotations

from app.scanners.base import Scanner
from app.scanners.dorks_scan import DorkScanner
from app.scanners.email_intel import EmailIntelScanner
from app.scanners.gravatar_scan import GravatarScanner
from app.scanners.harvester_scan import HarvesterScanner
from app.scanners.hibp_scan import HibpScanner
from app.scanners.holehe_scan import HoleheScanner
from app.scanners.numverify_scan import NumverifyScanner
from app.scanners.phone_scan import PhoneScanner
from app.scanners.sherlock_scan import SherlockScanner
from app.scanners.socialscan_scan import SocialscanScanner
from app.scanners.usernames import UsernameCandidateScanner


def all_scanners() -> list[Scanner]:
    return [
        UsernameCandidateScanner(),
        EmailIntelScanner(),
        GravatarScanner(),
        HoleheScanner(),
        SocialscanScanner(),
        SherlockScanner(),
        PhoneScanner(),
        HarvesterScanner(),
        DorkScanner(),
        HibpScanner(),
        NumverifyScanner(),
    ]
