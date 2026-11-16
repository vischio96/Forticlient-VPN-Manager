"""Fictitious tunnels used when FVM_DEMO=1 (documentation screenshots, UI testing).

Nothing here touches FortiClient.
"""
from __future__ import annotations

from .backend import (
    ORIGIN_EMS, ORIGIN_PERSONAL, PROTO_IPSEC, PROTO_SSL, STATUS_CONNECTED, STATUS_DISCONNECTED, Tunnel,
)

_IPSEC_EMS = [
    ("Sede Centrale - Full Tunnel", "vpn-hq.example.com", False),
    ("Sede Centrale - Split Tunnel", "vpn-hq.example.com", False),
    ("Filiale Milano - IPSEC", "203.0.113.10", False),
    ("Filiale Roma - IPSEC", "203.0.113.25", False),
    ("Filiale Torino - IPSEC", "198.51.100.7", False),
    ("Cliente Alfa - IPSEC-MFA", "alfa.vpn.example.net", False),
    ("Cliente Beta - IPSEC-SAML", "beta.vpn.example.net", True),
    ("Cliente Gamma - IPSEC-MFA", "gamma.vpn.example.net", False),
    ("Cliente Delta - IPSEC-MFA", "198.51.100.42", False),
    ("Datacenter - Management", "dc-mgmt.example.com", False),
]
_SSL_EMS = [
    ("Accesso Remoto Aziendale", "sslvpn.example.com:443", True),
    ("Accesso Remoto - Backup", "sslvpn2.example.com:443", False),
    ("Cliente Alfa - SSL", "alfa-ssl.example.net:10443", False),
    ("Cliente Epsilon - SSL", "epsilon.example.net:443", False),
    ("Cliente Zeta - SSO", "zeta.example.net:443", True),
    ("Laboratorio Test", "lab.example.com:4443", False),
    ("Cloud Hosting", "cloud.example.com:443", False),
]
_SSL_PERSONAL = [
    ("Casa - NAS", "home.example.org:4443", False),
    ("Ufficio Personale", "192.0.2.15:10443", False),
]


def tunnels() -> list[Tunnel]:
    out = [Tunnel(n, PROTO_IPSEC, ORIGIN_EMS, s, saml) for n, s, saml in _IPSEC_EMS]
    out += [Tunnel(n, PROTO_SSL, ORIGIN_EMS, s, saml) for n, s, saml in _SSL_EMS]
    out += [Tunnel(n, PROTO_SSL, ORIGIN_PERSONAL, s, saml) for n, s, saml in _SSL_PERSONAL]
    out.sort(key=lambda t: t.name.casefold())
    return out


def status() -> dict[str, str]:
    st = {t.name: STATUS_DISCONNECTED for t in tunnels()}
    st["Sede Centrale - Full Tunnel"] = STATUS_CONNECTED
    return st
