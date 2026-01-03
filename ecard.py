"""
Functions to get data from an e-card via a smartcard reader (offline).

Reads the "SV Personendaten" application and the "Grunddaten" EF (EF01),
then parses the DER/ASN.1 payload to extract:
(lastname, firstname, birthday_iso, insurance_svnr, sex)

Requirements:
    pip install pyscard
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple, Optional, Any, Dict
import re

from smartcard.System import readers
from smartcard.Exceptions import NoCardException


# --------------------------
# APDU / PCSC helpers
# --------------------------

@dataclass
class ApduResult:
    data: bytes
    sw1: int
    sw2: int

    @property
    def sw(self) -> int:
        return (self.sw1 << 8) | self.sw2

    def ok(self) -> bool:
        return self.sw == 0x9000


def _transmit(conn, apdu: List[int]) -> ApduResult:
    resp, sw1, sw2 = conn.transmit(apdu)
    return ApduResult(bytes(resp), sw1, sw2)


def _select_by_aid(conn, aid: List[int]) -> None:
    """
    SELECT by AID with fallbacks (some cards reject Le=FF -> 6700).
    Tries:
      - Case 3 (no Le)
      - Case 4 (Le=00 meaning 256)
      - Case 4 (Le=FF)
      - retries with 6Cxx suggested Le if needed
    """
    variants = [
        [0x00, 0xA4, 0x04, 0x00, len(aid)] + aid,
        [0x00, 0xA4, 0x04, 0x00, len(aid)] + aid + [0x00],
        [0x00, 0xA4, 0x04, 0x00, len(aid)] + aid + [0xFF],
    ]

    last: Optional[ApduResult] = None
    for apdu in variants:
        res = _transmit(conn, apdu)
        last = res
        if res.sw1 == 0x6C and len(apdu) >= 1:
            # wrong Le -> retry with suggested Le
            apdu2 = apdu[:-1] + [res.sw2]
            res = _transmit(conn, apdu2)
            last = res
        if res.ok():
            return

    raise RuntimeError(f"SELECT AID failed. Last SW={last.sw:04X}" if last else "SELECT AID failed.")


def _select_by_fid(conn, fid: List[int], p1: int = 0x02, p2: int = 0x04) -> ApduResult:
    variants = [
        [0x00, 0xA4, p1, p2, len(fid)] + fid,
        [0x00, 0xA4, p1, p2, len(fid)] + fid + [0x00],
        [0x00, 0xA4, p1, p2, len(fid)] + fid + [0xFF],
    ]

    last: Optional[ApduResult] = None
    for apdu in variants:
        res = _transmit(conn, apdu)
        last = res
        if res.sw1 == 0x6C and len(apdu) >= 1:
            apdu2 = apdu[:-1] + [res.sw2]
            res = _transmit(conn, apdu2)
            last = res
        if res.ok():
            return res

    raise RuntimeError(f"SELECT EF failed. Last SW={last.sw:04X}" if last else "SELECT EF failed.")


def _parse_fcp_file_size(fcp: bytes) -> Optional[int]:
    """
    Parse ISO7816 FCP (tag 0x62) to get file size (tag 0x80, sometimes 0x81/0x82).
    """
    if not fcp:
        return None

    # unwrap 0x62 if present
    if fcp[0] == 0x62 and len(fcp) >= 2:
        i = 1
        l = fcp[i]
        i += 1
        if l & 0x80:
            n = l & 0x7F
            l = int.from_bytes(fcp[i:i+n], "big")
            i += n
        fcp = fcp[i:i+l]

    def read_len(buf: bytes, idx: int) -> Tuple[int, int]:
        l2 = buf[idx]
        idx += 1
        if l2 & 0x80:
            n2 = l2 & 0x7F
            l2 = int.from_bytes(buf[idx:idx+n2], "big")
            idx += n2
        return l2, idx

    idx = 0
    while idx < len(fcp):
        tag = fcp[idx]
        idx += 1
        if idx >= len(fcp):
            break
        l3, idx = read_len(fcp, idx)
        value = fcp[idx:idx+l3]
        idx += l3
        if tag in (0x80, 0x81, 0x82) and l3 in (1, 2, 3, 4):
            return int.from_bytes(value, "big")

    return None


def _read_binary(conn, offset: int, le: int) -> ApduResult:
    p1 = (offset >> 8) & 0xFF
    p2 = offset & 0xFF
    return _transmit(conn, [0x00, 0xB0, p1, p2, le])


def _read_binary_all(conn, expected_len: Optional[int]) -> bytes:
    out = bytearray()
    offset = 0

    while True:
        if expected_len is not None:
            remaining = expected_len - len(out)
            if remaining <= 0:
                break
            le = min(0xFF, remaining)
        else:
            le = 0xFF

        res = _read_binary(conn, offset, le)
        if res.sw1 == 0x6C:
            res = _read_binary(conn, offset, res.sw2)

        if res.ok():
            if not res.data:
                break
            out += res.data
            offset += len(res.data)

            if expected_len is not None and len(out) >= expected_len:
                out = out[:expected_len]
                break
            continue

        if res.sw == 0x6B00:
            break

        raise RuntimeError(f"READ BINARY failed at offset {offset}: SW={res.sw:04X}")

    return bytes(out)


# --------------------------
# Minimal DER parsing for Grunddaten payload
# --------------------------

class DerError(Exception):
    pass


def _der_read_length(buf: bytes, i: int) -> Tuple[int, int]:
    if i >= len(buf):
        raise DerError("Unexpected end while reading length")
    first = buf[i]
    i += 1
    if first < 0x80:
        return first, i
    n = first & 0x7F
    if n == 0 or n > 4:
        raise DerError(f"Unsupported length octets: {n}")
    if i + n > len(buf):
        raise DerError("Unexpected end in long-form length")
    length = int.from_bytes(buf[i:i+n], "big")
    return length, i + n


def _der_read_tlv(buf: bytes, i: int) -> Tuple[int, int, bytes, int]:
    if i >= len(buf):
        raise DerError("Unexpected end while reading tag")
    tag = buf[i]
    i += 1
    length, i = _der_read_length(buf, i)
    if i + length > len(buf):
        raise DerError("Length exceeds buffer")
    value = buf[i:i+length]
    return tag, length, value, i + length


def _der_decode_oid(oid_bytes: bytes) -> str:
    if not oid_bytes:
        return ""
    first = oid_bytes[0]
    arcs = [first // 40, first % 40]
    value = 0
    for b in oid_bytes[1:]:
        value = (value << 7) | (b & 0x7F)
        if not (b & 0x80):
            arcs.append(value)
            value = 0
    return ".".join(str(a) for a in arcs)


def _der_decode_value(tag: int, value: bytes) -> Any:
    if tag == 0x0C:  # UTF8String
        return value.decode("utf-8", errors="replace")
    if tag == 0x13:  # PrintableString
        return value.decode("ascii", errors="replace")
    if tag == 0x16:  # IA5String
        return value.decode("ascii", errors="replace")
    if tag == 0x18:  # GeneralizedTime
        return value.decode("ascii", errors="replace")
    if tag == 0x02:  # Integer
        return int.from_bytes(value, "big", signed=False)
    return value  # keep bytes


def _try_extract_digits(v: Any) -> Optional[str]:
    if isinstance(v, str):
        m = re.search(r"\b(\d{10})\b", v)
        return m.group(1) if m else None
    if isinstance(v, (bytes, bytearray)):
        s = bytes(v).decode("ascii", errors="ignore")
        m = re.search(r"\b(\d{10})\b", s)
        return m.group(1) if m else None
    return None


def _normalize_birthdate(gt: Optional[str]) -> Optional[str]:
    if not gt or not isinstance(gt, str):
        return None
    m = re.match(r"^(\d{4})(\d{2})(\d{2})", gt)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def _normalize_sex(raw: Any) -> str:
    """Normalize gender/sex values to the app's allowed strings.

    The UI/backend in this project expects:
      - "Male"
      - "Female"
      - "" (unspecified / None/Other)

    e-card / certificates can encode gender in different ways (letters, words,
    or ISO/IEC 5218 numeric codes). We normalize the most common variants.
    """

    if raw is None:
        return ""

    s = str(raw).strip()
    if not s:
        return ""

    # ISO/IEC 5218 codes are sometimes used:
    # 0=not known, 1=male, 2=female, 9=not applicable
    if s in {"0", "9"}:
        return ""
    if s == "1":
        return "Male"
    if s == "2":
        return "Female"

    upper = s.upper()
    lower = s.lower()

    # Single-letter variants
    if upper == "M":
        return "Male"
    if upper == "F":
        return "Female"
    if upper in {"X", "D", "U"}:
        return ""

    # Word / localized variants
    if lower in {"male", "männlich", "maennlich", "mann", "masculine"}:
        return "Male"
    if lower in {"female", "weiblich", "frau", "feminine"}:
        return "Female"
    if lower in {"divers", "diverse", "other", "none", "unknown", "unspecified", "not known", "not applicable"}:
        return ""

    # If we don't recognize it, prefer not failing registration.
    return ""


def _parse_grunddaten(blob: bytes) -> Dict[str, Any]:
    """
    Parses the Grunddaten DER structure:
      SEQUENCE of SEQUENCE { OID, SET { value } }
    Extracts:
      - givenName (2.5.4.42)
      - surname (2.5.4.4)
      - dateOfBirth (1.3.6.1.5.5.7.9.1)
      - gender (1.3.6.1.5.5.7.9.3)
      - SVNR (heuristic: any 10-digit sequence in values)
    """
    out: Dict[str, Any] = {
        "svnr": None,
        "given_name": None,
        "surname": None,
        "birthdate_iso": None,
        "gender": None,
        "raw_oids": {},
    }

    tag, _, val, _ = _der_read_tlv(blob, 0)
    if tag != 0x30:
        raise DerError(f"Expected outer SEQUENCE (0x30), got {tag:02X}")

    i = 0
    while i < len(val):
        t1, _, v1, i = _der_read_tlv(val, i)
        if t1 != 0x30:
            continue

        j = 0
        t_oid, _, v_oid, j = _der_read_tlv(v1, j)
        if t_oid != 0x06:
            continue
        oid = _der_decode_oid(v_oid)

        parsed_value = None
        if j < len(v1):
            t_set, _, v_set, _ = _der_read_tlv(v1, j)
            if t_set == 0x31 and len(v_set) > 0:
                t_val, _, v_val, _ = _der_read_tlv(v_set, 0)
                parsed_value = _der_decode_value(t_val, v_val)

        out["raw_oids"][oid] = parsed_value

        if oid == "2.5.4.42":
            out["given_name"] = parsed_value
        elif oid == "2.5.4.4":
            out["surname"] = parsed_value
        elif oid == "1.3.6.1.5.5.7.9.1":
            out["birthdate_iso"] = _normalize_birthdate(parsed_value if isinstance(parsed_value, str) else None)
        elif oid == "1.3.6.1.5.5.7.9.3":
            out["gender"] = parsed_value

        if out["svnr"] is None:
            cand = _try_extract_digits(parsed_value)
            if cand:
                out["svnr"] = cand

    # Ensure pure strings
    if isinstance(out["given_name"], bytes):
        out["given_name"] = out["given_name"].decode("utf-8", errors="replace")
    if isinstance(out["surname"], bytes):
        out["surname"] = out["surname"].decode("utf-8", errors="replace")
    if isinstance(out["gender"], bytes):
        out["gender"] = out["gender"].decode("ascii", errors="ignore")

    return out


# --------------------------
# Public API
# --------------------------

def is_card_present() -> bool:
    return False
    #Due to bugs, this function doesnt quite work.
    """
    Check if any connected reader has a card inserted.
    Returns True if at least one reader has a card.
    """
    try:
        r = readers()
        if not r:
            return False
        for reader in r:
            # pyscard readers usually have isCardPresent()
            if hasattr(reader, "isCardPresent"):
                if reader.isCardPresent():
                    return True
            else:
                # Fallback: try to connect
                try:
                    conn = reader.createConnection()
                    conn.connect()
                    return True
                except NoCardException:
                    pass
                except Exception:
                    pass
        return False
    except Exception:
        return False


def read_data() -> tuple[str, str, str, str, str]:
    """
    Read offline data from an Austrian e-card.

    Returns: (lastname, firstname, birthday_iso, insurance_svnr, sex)
    sex is returned as "Male"/"Female" when present; otherwise empty string.
    """
    # Pick a reader (see notes below)
    r = readers()
    if not r:
        raise RuntimeError("No PC/SC smartcard readers found (check driver / Windows Smart Card service).")
    reader = r[0]

    conn = reader.createConnection()
    try:
        conn.connect()
    except NoCardException:
        raise RuntimeError("Reader found, but no card is inserted.")

    # APDU sequence you provided:
    # 1) SELECT application "SV Personendaten" by AID
    aid_sv_personendaten = [0xD0, 0x40, 0x00, 0x00, 0x17, 0x01, 0x01, 0x01]
    _select_by_aid(conn, aid_sv_personendaten)

    # 2) SELECT EF "Grunddaten" (EF01) and parse file size from FCP
    fid_grunddaten = [0xEF, 0x01]
    sel = _select_by_fid(conn, fid_grunddaten, p1=0x02, p2=0x04)
    expected_len = _parse_fcp_file_size(sel.data)

    # 3) READ BINARY (whole EF)
    blob = _read_binary_all(conn, expected_len=expected_len)

    # Parse DER/ASN.1
    parsed = _parse_grunddaten(blob)

    lastname = str(parsed.get("surname") or "")
    firstname = str(parsed.get("given_name") or "")
    birthday = str(parsed.get("birthdate_iso") or "")
    insurance = str(parsed.get("svnr") or "")
    # Format as xxxx/ddmmyy if 10 digits
    if len(insurance) == 10 and insurance.isdigit():
        insurance = f"{insurance[:4]}/{insurance[4:]}"

    sex = _normalize_sex(parsed.get("gender"))

    return (lastname, firstname, birthday, insurance, sex)


if __name__ == "__main__":
    print("Checking for card presence...")
    if is_card_present():
        print("Card detected!")
        try:
            print("Reading data...")
            data = read_data()
            print("-" * 20)
            print(f"Lastname:  {data[0]}")
            print(f"Firstname: {data[1]}")
            print(f"Birthday:  {data[2]}")
            print(f"SVNR:      {data[3]}")
            print(f"Sex:       {data[4]}")
            print("-" * 20)
        except Exception as e:
            print(f"Error reading card: {e}")
    else:
        print("No card detected in any reader.")
