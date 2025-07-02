# cable_diag.py – SNMP‑TDR для SNR/Eltex и D‑Link (без SSH)

"""Мини‑модуль запускает кабельную диагностику через SNMP.
Работает напрямую на UDP‑161. Если доступ разрешён только с «доверенного»
IP, то бот должен быть запущен там или трафик должен натироваться.
"""

from pysnmp.hlapi import *  # noqa: F401,F403 – групповое подключение
import re
import time
from typing import List

DEFAULT_COMMUNITY = "public"
WAIT_SEC = 20  # макс. ожидание завершения TDR, сек

# ──────────────────────────── карты статусов ────────────────────────────────
DLINK_STATUS_MAP = {
    0: "ok",
    1: "open",
    2: "short",
    3: "open-short",
    4: "crosstalk",
    5: "unknown",
    6: "count",
    7: "no-cable",
    8: "other",
}

SNR_STATUS_MAP = {
    0: "fail", 1: "ok", 2: "open", 3: "short", 4: "impedance",
    5: "short-p1", 6: "short-p2", 7: "short-p3", 8: "short-p4",
}

# ─────────────────────────── SNMP helpers ───────────────────────────────────

def _snmp_get(ip: str, community: str, oid: str, timeout: int = 4) -> int:
    errInd, errStat, _, varBinds = next(
        getCmd(
            SnmpEngine(), CommunityData(community),
            UdpTransportTarget((ip, 161), timeout=timeout, retries=2),
            ContextData(), ObjectType(ObjectIdentity(oid))
        )
    )
    if errInd:
        raise RuntimeError(errInd)
    if errStat:
        raise RuntimeError(errStat.prettyPrint())
    return int(varBinds[0][1])


def _snmp_set(ip: str, community: str, oid: str, value: int, timeout: int = 4):
    errInd, errStat, _, _ = next(
        setCmd(
            SnmpEngine(), CommunityData(community),
            UdpTransportTarget((ip, 161), timeout=timeout, retries=2),
            ContextData(), ObjectType(ObjectIdentity(oid), Integer(value))
        )
    )
    if errInd:
        raise RuntimeError(errInd)
    if errStat:
        raise RuntimeError(errStat.prettyPrint())

# ───────────────────────────── SNR / Eltex ──────────────────────────────────

def _diag_snr(ip: str, port: str, community: str) -> str:
    """TDR для SNR/Eltex – enterprise 35265 (eltPhyTdr*)."""
    m = re.search(r"(\d+)$", port)
    if not m:
        return f"⚠️ Порт '{port}' не распознан"
    ifindex = int(m.group(1))

    start_oid = f"1.3.6.1.4.1.35265.1.23.90.1.1.1.3.{ifindex}"
    try:
        _snmp_set(ip, community, start_oid, 2)
    except Exception:
        pass  # на старых прошивках запуск не требуется

    # ждём, пока результат валиден или истечёт WAIT_SEC
    for _ in range(WAIT_SEC):):
        try:
            valid = _snmp_get(ip, community, f"1.3.6.1.4.1.35265.1.23.90.1.1.1.1.{ifindex}")
            if valid == 1:
                break
        except Exception:
            pass
        time.sleep(1)

    res: List[str] = []
    for p in range(1, 5):
        st_oid = f"1.3.6.1.4.1.35265.1.23.90.1.1.1.{1+p}.{ifindex}"  # .2-.5
        ln_oid = f"1.3.6.1.4.1.35265.1.23.90.1.1.1.{5+p}.{ifindex}"  # .6-.9
        try:
            st = _snmp_get(ip, community, st_oid)
            ln = _snmp_get(ip, community, ln_oid)
            res.append(f"pair{p}: {SNR_STATUS_MAP.get(st, st)} {ln} м")
        except Exception as e:
            res.append(f"pair{p}: ❌ {e}")
    return "\n".join(res)

# ────────────────────────────── D‑Link ──────────────────────────────────────

def _diag_dlink(ip: str, port: str, community: str) -> str:
    """TDR для D‑Link – enterprise 171.12.58."""
    m = re.search(r"(\d+)$", port)
    if not m:
        return f"⚠️ Порт '{port}' не распознан"
    ifindex = int(m.group(1))

    start_oid = f"1.3.6.1.4.1.171.12.58.1.1.1.12.{ifindex}"
    try:
        _snmp_set(ip, community, start_oid, 1)
    except Exception as e:
        return f"❌ set: {e}"

    # ждём, пока статус перестанет быть processing, макс WAIT_SEC
    for _ in range(WAIT_SEC):
        try:
            act = _snmp_get(ip, community, start_oid)
            if act != 2:  # 2 = processing
                break
        except Exception:
            pass
        time.sleep(1)

    res: List[str] = []
    for p in range(1, 5):
        st_oid = f"1.3.6.1.4.1.171.12.58.1.1.1.{3+p}.{ifindex}"  # .4-.7
        ln_oid = f"1.3.6.1.4.1.171.12.58.1.1.1.{7+p}.{ifindex}"  # .8-.11
        try:
            st = _snmp_get(ip, community, st_oid)
            ln = _snmp_get(ip, community, ln_oid)
            res.append(f"pair{p}: {DLINK_STATUS_MAP.get(st, st)} {ln} м")
        except Exception as e:
            res.append(f"pair{p}: ❌ {e}")
    return "\n".join(res)

# ───────────────────────────── публичный API ────────────────────────────────

def run_cable_diag(ip: str, port: str, family: str, community: str = DEFAULT_COMMUNITY) -> str:
    if family == "snr":
        return _diag_snr(ip, port, community)
    if family == "dlink":
        return _diag_dlink(ip, port, community)
    return "⚠️ Пока без поддержки этого семейства"
