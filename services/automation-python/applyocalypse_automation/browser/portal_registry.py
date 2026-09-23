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


# Every portal here names "playwright", the Patchright-driven adapter, and it has to
# stay an adapter that actually ships. These entries once said "playwright" while
# Playwright was neither a dependency nor bundled by the PyInstaller build, so on a
# real install the launch failed and every run fell through to another driver without
# saying so. test_portal_registry.py asserts that every default_adapter is importable,
# so this cannot drift silently. nodriver used to be the default here; it was removed
# because its AGPL-3.0 licence could not ship and it had no path to parity on macOS.
# See plans/portal-filling-audit.md.
PORTALS: tuple[PortalDefinition, ...] = (
    PortalDefinition("indeed", "Indeed", ("indeed.com",), "playwright", True),
    PortalDefinition("glassdoor", "Glassdoor", ("glassdoor.com",), "playwright", True),
    PortalDefinition("ziprecruiter", "ZipRecruiter", ("ziprecruiter.com",), "playwright", True),
    PortalDefinition("dice", "Dice", ("dice.com",), "playwright", True),
    PortalDefinition("wellfound", "Wellfound", ("wellfound.com", "angel.co"), "playwright", True),
    PortalDefinition("otta", "Otta", ("otta.com",), "playwright", True),
    PortalDefinition("careerbuilder", "CareerBuilder", ("careerbuilder.com",), "playwright", True),
    PortalDefinition("monster", "Monster", ("monster.com",), "playwright", True),
    PortalDefinition("usajobs", "USAJobs", ("usajobs.gov",), "playwright", False),
    PortalDefinition("governmentjobs", "GovernmentJobs", ("governmentjobs.com",), "playwright", False),
    PortalDefinition("linkedin", "LinkedIn", ("linkedin.com",), "playwright", True),
    PortalDefinition("naukri", "Naukri", ("naukri.com",), "playwright", True),
    PortalDefinition("instahyre", "Instahyre", ("instahyre.com",), "playwright", True),
    PortalDefinition("hirist", "Hirist", ("hirist.tech", "hirist.com"), "playwright", True),
    PortalDefinition("iimjobs", "IIMjobs", ("iimjobs.com",), "playwright", True),
    PortalDefinition("foundit", "Foundit", ("foundit.in",), "playwright", True),
    PortalDefinition("shine", "Shine", ("shine.com",), "playwright", True),
    PortalDefinition("timesjobs", "TimesJobs", ("timesjobs.com",), "playwright", True),
    PortalDefinition("freshersworld", "Freshersworld", ("freshersworld.com",), "playwright", True),
    PortalDefinition("ncs", "NCS", ("ncs.gov.in",), "playwright", False),
    PortalDefinition("workday", "Workday", ("myworkdayjobs.com", "workdayjobs.com"), "playwright", False),
    PortalDefinition("greenhouse", "Greenhouse", ("greenhouse.io", "greenhouse.com"), "playwright", False),
    PortalDefinition("lever", "Lever", ("lever.co",), "playwright", False),
    PortalDefinition("ashby", "Ashby", ("ashbyhq.com",), "playwright", False),
    PortalDefinition("icims", "iCIMS", ("icims.com",), "playwright", False),
    PortalDefinition("taleo", "Taleo", ("taleo.net",), "playwright", False),
    # Mid-market and enterprise ATSes. Each is its own DOM, but all of them serve
    # an ordinary form: leaving them unregistered was the expensive part, because
    # an unknown host falls through to the stealth job-board path, which refuses to
    # detect a single field until a human confirms the page. Registering one only
    # says "this host is an ATS, here is its apply button" - the review gates and the
    # submit gate are unchanged.
    PortalDefinition("workable", "Workable", ("workable.com",), "playwright", False),
    PortalDefinition("smartrecruiters", "SmartRecruiters", ("smartrecruiters.com",), "playwright", False),
    PortalDefinition("jobvite", "Jobvite", ("jobvite.com",), "playwright", False),
    PortalDefinition("bamboohr", "BambooHR", ("bamboohr.com",), "playwright", False),
    # JazzHR boards are served from applytojob.com, not from a jazzhr.com host.
    PortalDefinition("jazzhr", "JazzHR", ("applytojob.com",), "playwright", False),
    PortalDefinition("breezy", "Breezy HR", ("breezy.hr",), "playwright", False),
    PortalDefinition("recruitee", "Recruitee", ("recruitee.com",), "playwright", False),
    PortalDefinition("teamtailor", "Teamtailor", ("teamtailor.com",), "playwright", False),
    PortalDefinition("pinpoint", "Pinpoint", ("pinpointhq.com",), "playwright", False),
    PortalDefinition("rippling", "Rippling", ("rippling.com",), "playwright", False),
    PortalDefinition("successfactors", "SAP SuccessFactors", ("successfactors.com", "successfactors.eu"), "playwright", False),
    # Oracle Recruiting Cloud lives under a tenant subdomain of oraclecloud.com;
    # legacy iRecruitment instances still answer on oracle.com hosts.
    PortalDefinition("oraclecloud", "Oracle Recruiting Cloud", ("oraclecloud.com",), "playwright", False),
    PortalDefinition("adp", "ADP Recruiting", ("myjobs.adp.com", "workforcenow.adp.com"), "playwright", False),
    PortalDefinition("ultipro", "UKG / UltiPro", ("ultipro.com", "ukg.com"), "playwright", False),
    PortalDefinition("paylocity", "Paylocity", ("paylocity.com",), "playwright", False),
    PortalDefinition("paycom", "Paycom", ("paycomonline.net",), "playwright", False),
    PortalDefinition("avature", "Avature", ("avature.net",), "playwright", False),
    PortalDefinition("bullhorn", "Bullhorn", ("bullhornstaffing.com", "bullhorncdn.com"), "playwright", False),
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
