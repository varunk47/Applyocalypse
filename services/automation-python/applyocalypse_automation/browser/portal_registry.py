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


PORTALS: tuple[PortalDefinition, ...] = (
    PortalDefinition("indeed", "Indeed", ("indeed.com",), "nodriver", True),
    PortalDefinition("glassdoor", "Glassdoor", ("glassdoor.com",), "nodriver", True),
    PortalDefinition("ziprecruiter", "ZipRecruiter", ("ziprecruiter.com",), "nodriver", True),
    PortalDefinition("dice", "Dice", ("dice.com",), "nodriver", True),
    PortalDefinition("wellfound", "Wellfound", ("wellfound.com", "angel.co"), "nodriver", True),
    PortalDefinition("otta", "Otta", ("otta.com",), "nodriver", True),
    PortalDefinition("careerbuilder", "CareerBuilder", ("careerbuilder.com",), "nodriver", True),
    PortalDefinition("monster", "Monster", ("monster.com",), "nodriver", True),
    PortalDefinition("usajobs", "USAJobs", ("usajobs.gov",), "playwright", False),
    PortalDefinition("governmentjobs", "GovernmentJobs", ("governmentjobs.com",), "playwright", False),
    PortalDefinition("linkedin", "LinkedIn", ("linkedin.com",), "nodriver", True),
    PortalDefinition("naukri", "Naukri", ("naukri.com",), "nodriver", True),
    PortalDefinition("instahyre", "Instahyre", ("instahyre.com",), "nodriver", True),
    PortalDefinition("hirist", "Hirist", ("hirist.tech", "hirist.com"), "nodriver", True),
    PortalDefinition("iimjobs", "IIMjobs", ("iimjobs.com",), "nodriver", True),
    PortalDefinition("foundit", "Foundit", ("foundit.in",), "nodriver", True),
    PortalDefinition("shine", "Shine", ("shine.com",), "nodriver", True),
    PortalDefinition("timesjobs", "TimesJobs", ("timesjobs.com",), "nodriver", True),
    PortalDefinition("freshersworld", "Freshersworld", ("freshersworld.com",), "nodriver", True),
    PortalDefinition("ncs", "NCS", ("ncs.gov.in",), "playwright", False),
    PortalDefinition("workday", "Workday", ("myworkdayjobs.com", "workdayjobs.com"), "playwright", False),
    PortalDefinition("greenhouse", "Greenhouse", ("greenhouse.io", "greenhouse.com"), "playwright", False),
    PortalDefinition("lever", "Lever", ("lever.co",), "playwright", False),
    PortalDefinition("ashby", "Ashby", ("ashbyhq.com",), "playwright", False),
    PortalDefinition("icims", "iCIMS", ("icims.com",), "playwright", False),
    PortalDefinition("taleo", "Taleo", ("taleo.net",), "playwright", False),
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
