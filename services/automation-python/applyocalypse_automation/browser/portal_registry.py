from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class PortalDefinition:
    portal_id: str
    display_name: str
    domains: tuple[str, ...]
    default_adapter: str
    requires_high_stealth: bool


# Every portal here names "nodriver", and it has to stay an adapter that actually
# ships. These entries used to say "playwright", which at the time was not a
# dependency of this project and was not bundled by the PyInstaller build, so on a
# real install the launch failed and every run fell through to nodriver without
# saying so. The damage was not the fallback, it was that the Playwright-only work
# (cross-origin frame enumeration) was never the code a user ran.
# test_portal_registry.py asserts that every default_adapter is importable, so this
# cannot drift back silently. The Playwright adapter now ships too, driven by
# Patchright, and sits second in the fallback chain; nodriver stays the declared
# default because it is the one with the hand-built CDP stealth path.
# See plans/portal-filling-audit.md.
PORTALS: tuple[PortalDefinition, ...] = (
    PortalDefinition("indeed", "Indeed", ("indeed.com",), "nodriver", True),
    PortalDefinition("glassdoor", "Glassdoor", ("glassdoor.com",), "nodriver", True),
    PortalDefinition("ziprecruiter", "ZipRecruiter", ("ziprecruiter.com",), "nodriver", True),
    PortalDefinition("dice", "Dice", ("dice.com",), "nodriver", True),
    PortalDefinition("wellfound", "Wellfound", ("wellfound.com", "angel.co"), "nodriver", True),
    PortalDefinition("otta", "Otta", ("otta.com",), "nodriver", True),
    PortalDefinition("careerbuilder", "CareerBuilder", ("careerbuilder.com",), "nodriver", True),
    PortalDefinition("monster", "Monster", ("monster.com",), "nodriver", True),
    PortalDefinition("usajobs", "USAJobs", ("usajobs.gov",), "nodriver", False),
    PortalDefinition("governmentjobs", "GovernmentJobs", ("governmentjobs.com",), "nodriver", False),
    PortalDefinition("linkedin", "LinkedIn", ("linkedin.com",), "nodriver", True),
    PortalDefinition("naukri", "Naukri", ("naukri.com",), "nodriver", True),
    PortalDefinition("instahyre", "Instahyre", ("instahyre.com",), "nodriver", True),
    PortalDefinition("hirist", "Hirist", ("hirist.tech", "hirist.com"), "nodriver", True),
    PortalDefinition("iimjobs", "IIMjobs", ("iimjobs.com",), "nodriver", True),
    PortalDefinition("foundit", "Foundit", ("foundit.in",), "nodriver", True),
    PortalDefinition("shine", "Shine", ("shine.com",), "nodriver", True),
    PortalDefinition("timesjobs", "TimesJobs", ("timesjobs.com",), "nodriver", True),
    PortalDefinition("freshersworld", "Freshersworld", ("freshersworld.com",), "nodriver", True),
    PortalDefinition("ncs", "NCS", ("ncs.gov.in",), "nodriver", False),
    PortalDefinition("workday", "Workday", ("myworkdayjobs.com", "workdayjobs.com"), "nodriver", False),
    PortalDefinition("greenhouse", "Greenhouse", ("greenhouse.io", "greenhouse.com"), "nodriver", False),
    PortalDefinition("lever", "Lever", ("lever.co",), "nodriver", False),
    PortalDefinition("ashby", "Ashby", ("ashbyhq.com",), "nodriver", False),
    PortalDefinition("icims", "iCIMS", ("icims.com",), "nodriver", False),
    PortalDefinition("taleo", "Taleo", ("taleo.net",), "nodriver", False),
    # Mid-market and enterprise ATSes. Each is its own DOM, but all of them serve
    # an ordinary form: leaving them unregistered was the expensive part, because
    # an unknown host falls through to the stealth job-board path, which opens
    # Nodriver and refuses to detect a single field until a human confirms the
    # page. Registering one only says "this host is an ATS, here is its apply
    # button" - the review gates and the submit gate are unchanged.
    PortalDefinition("workable", "Workable", ("workable.com",), "nodriver", False),
    PortalDefinition("smartrecruiters", "SmartRecruiters", ("smartrecruiters.com",), "nodriver", False),
    PortalDefinition("jobvite", "Jobvite", ("jobvite.com",), "nodriver", False),
    PortalDefinition("bamboohr", "BambooHR", ("bamboohr.com",), "nodriver", False),
    # JazzHR boards are served from applytojob.com, not from a jazzhr.com host.
    PortalDefinition("jazzhr", "JazzHR", ("applytojob.com",), "nodriver", False),
    PortalDefinition("breezy", "Breezy HR", ("breezy.hr",), "nodriver", False),
    PortalDefinition("recruitee", "Recruitee", ("recruitee.com",), "nodriver", False),
    PortalDefinition("teamtailor", "Teamtailor", ("teamtailor.com",), "nodriver", False),
    PortalDefinition("pinpoint", "Pinpoint", ("pinpointhq.com",), "nodriver", False),
    PortalDefinition("rippling", "Rippling", ("rippling.com",), "nodriver", False),
    PortalDefinition("successfactors", "SAP SuccessFactors", ("successfactors.com", "successfactors.eu"), "nodriver", False),
    # Oracle Recruiting Cloud lives under a tenant subdomain of oraclecloud.com;
    # legacy iRecruitment instances still answer on oracle.com hosts.
    PortalDefinition("oraclecloud", "Oracle Recruiting Cloud", ("oraclecloud.com",), "nodriver", False),
    PortalDefinition("adp", "ADP Recruiting", ("myjobs.adp.com", "workforcenow.adp.com"), "nodriver", False),
    PortalDefinition("ultipro", "UKG / UltiPro", ("ultipro.com", "ukg.com"), "nodriver", False),
    PortalDefinition("paylocity", "Paylocity", ("paylocity.com",), "nodriver", False),
    PortalDefinition("paycom", "Paycom", ("paycomonline.net",), "nodriver", False),
    PortalDefinition("avature", "Avature", ("avature.net",), "nodriver", False),
    PortalDefinition("bullhorn", "Bullhorn", ("bullhornstaffing.com", "bullhorncdn.com"), "nodriver", False),
)


def detect_portal(url: str) -> PortalDefinition | None:
    host = urlparse(url).hostname
    if not host:
        return None
    host = host.lower()
    for portal in PORTALS:
        if any(host == domain or host.endswith(f".{domain}") for domain in portal.domains):
            return portal
    return None
