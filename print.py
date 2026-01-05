"""
print.py

adds a printing uitility for a reciept printer
"""

from __future__ import annotations

import time
from typing import Optional

import Patient


CHARS_PER_LINE = 32
CODEPAGE = "CP437"  # common default for ESC/POS; change if your printer needs another


def _transliterate_german(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    repl = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "Ä": "Ae",
        "Ö": "Oe",
        "Ü": "Ue",
        "ß": "ss",
    }
    for k, v in repl.items():
        text = text.replace(k, v)
    return text


def wrap_text(text: str, max_chars: int) -> str:
    """Wrap text to max_chars per line, preferring spaces."""
    if not isinstance(text, str):
        text = str(text)
    if max_chars <= 0:
        return text

    paragraphs = text.split("\n")
    out_lines: list[str] = []
    for para in paragraphs:
        if not para:
            out_lines.append("")
            continue
        i = 0
        length = len(para)
        while i < length:
            chunk = para[i : i + max_chars]
            if len(chunk) < max_chars or i + max_chars >= length:
                out_lines.append(chunk)
                break
            last_space = chunk.rfind(" ")
            if last_space > 0:
                out_lines.append(chunk[:last_space])
                i += last_space + 1
            else:
                out_lines.append(chunk)
                i += max_chars
    return "\n".join(out_lines)


def _get_escpos_printer(printer_name: str):
    """Return an ESC/POS printer instance for a Windows printer name.

    Requires `python-escpos`.
    """
    from escpos.printer import Win32Raw  # type: ignore

    p = Win32Raw(printer_name)
    # Reset and codepage best-effort
    try:
        p.hw("INIT")
    except Exception:
        pass
    try:
        p.charcode(CODEPAGE)
    except Exception:
        pass
    return p


def _escpos_job(printer_name: str, job_fn) -> None:
    """Run a single ESC/POS print job.

    Some Windows receipt printer drivers latch formatting (double width/height)
    until the next spool job. By starting a fresh Win32Raw instance per section,
    we ensure format changes (big/normal) reliably apply.
    """
    p = _get_escpos_printer(printer_name)
    try:
        job_fn(p)
    finally:
        try:
            p.close()
        except Exception:
            pass


def _escpos_text(
    p,
    text: str,
    *,
    font_size: str = "normal",
    bold: bool = False,
    align: str = "left",
    double_width: bool | None = None,
    double_height: bool | None = None,
) -> None:
    text = _transliterate_german(text)

    if font_size == "small":
        default_dw, default_dh, font = False, False, "b"
    elif font_size == "big":
        default_dw, default_dh, font = True, True, None
    else:
        default_dw, default_dh, font = False, False, "a"

    dw = default_dw if double_width is None else bool(double_width)
    dh = default_dh if double_height is None else bool(double_height)

    kwargs = {"align": align, "bold": bold, "double_width": dw, "double_height": dh}
    if font is not None:
        kwargs["font"] = font
    try:
        p.set(**kwargs)
    except Exception:
        # Some drivers ignore/limit some style flags; best-effort
        p.set(align=align, bold=bold)

    p.text(text.rstrip("\n") + "\n")


def PatPrint(
    printer_name: str,
    patient: Patient.Patient,
    *,
    patient_id: Optional[int] = None,
    group_name: Optional[str] = None,
    base_url: str = "",
    is_update: bool = False,
    labels: dict[str, str] | None = None,
) -> None:
    """Print a patient label to an ESC/POS receipt printer.

    Required:
    - printer_name: Windows printer name (as seen in Settings -> Printers)
    - patient: instance of your existing Patient.Patient class

    Optional:
    - patient_id: numeric patient id (used in header + QR URL)
    - base_url: server base URL, e.g. https://example/coceso (used for QR URL)
    - is_update: if True, prints an "UPDATED" label
    - labels: dictionary of localized strings

    If the printer backend is unavailable, it falls back to console output.
    """
    labels = labels or {}
    l_insurance = labels.get("print_insurance", "Insurance")
    l_birth = labels.get("print_birth", "Birth")
    l_id = labels.get("print_id", "ID")
    l_ext_id = labels.get("print_ext_id", "Ext.ID")
    l_pat = labels.get("print_pat", "Pat.")
    l_updated = labels.get("print_updated", "(UPDATED)")

    lastname = getattr(patient, "lastname", "") or ""
    firstname = getattr(patient, "firstname", "") or ""
    external_id = getattr(patient, "external_id", "") or ""
    insurance = getattr(patient, "insurance", "") or ""
    birthday_raw = getattr(patient, "birthday", "") or ""
    group_id = getattr(patient, "group_id", "")
    patient_group_name = getattr(patient, "group_name", None)

    admintime = time.strftime("%H:%M")
    admindate = time.strftime("%d.%m.%Y")

    name_line = f"{lastname}, {firstname}".strip(", ")

    # Print birthdate in a friendly format if it looks like YYYY-MM-DD
    birthday_print = str(birthday_raw).strip()
    if len(birthday_print) == 10 and birthday_print[4] == "-" and birthday_print[7] == "-":
        yyyy, mm, dd = birthday_print[0:4], birthday_print[5:7], birthday_print[8:10]
        if yyyy.isdigit() and mm.isdigit() and dd.isdigit():
            birthday_print = f"{dd}.{mm}.{yyyy}"

    medium_lines: list[str] = []
    if insurance:
        medium_lines.append(f"{l_insurance}: {insurance}")
    if birthday_print:
        medium_lines.append(f"{l_birth}: {birthday_print}")
    medium_text = "\n".join(medium_lines)
    group_line = (
        (group_name or "").strip()
        or (str(patient_group_name).strip() if patient_group_name is not None else "")
        or (str(group_id).strip() if group_id is not None else "")
    )
    body_big = f"{group_line}\n{admindate} {admintime}".strip()

    pid_display = str(patient_id) if patient_id is not None else "-"
    body_small_lines = []
    body_small_lines.append(f"{l_id}:{pid_display}")
    if external_id:
        body_small_lines.append(f"{l_ext_id}:{external_id}")
    body_small = "\n".join(body_small_lines)

    edit_url = ""
    if base_url and patient_id is not None:
        edit_url = f"{base_url.rstrip('/')}/patadmin/treatment/view/{patient_id}"

    div = "-" * min(CHARS_PER_LINE, 32)

    # Try ESC/POS printing; if missing/fails, console fallback
    try:
        header_text = f"{l_pat} {pid_display}"
        if is_update:
            header_text += f" {l_updated}"

        # Job 1: header (big but narrow, not bold)
        _escpos_job(
            printer_name,
            lambda p: _escpos_text(
                p,
                header_text,
                font_size="big",
                bold=False,
                align="center",
                double_width=False,
                double_height=True,
            ),
        )
        # Divider in its own job (small)
        _escpos_job(printer_name, lambda p: _escpos_text(p, div, font_size="small"))

        # Job 2: name (big + bold)
        name_wrapped = wrap_text(name_line, 16).split("\n") if name_line else []
        _escpos_job(
            printer_name,
            lambda p: (
                [_escpos_text(p, ln, font_size="big", bold=True) for ln in name_wrapped],
            ),
        )

        # Job 2a: insurance + birthdate (medium / normal)
        if medium_text:
            medium_wrapped = wrap_text(medium_text, 32).split("\n")

            def _job2a(p):
                for ln in medium_wrapped:
                    _escpos_text(p, ln, font_size="normal", bold=False)

            _escpos_job(printer_name, _job2a)

        _escpos_job(printer_name, lambda p: _escpos_text(p, div, font_size="small"))

        # Job 3: group/date/time (big)
        big_wrapped = wrap_text(body_big, 16).split("\n") if body_big else []
        _escpos_job(
            printer_name,
            lambda p: (
                [_escpos_text(p, ln, font_size="big", bold=False) for ln in big_wrapped],
            ),
        )
        _escpos_job(printer_name, lambda p: _escpos_text(p, div, font_size="small"))

        # Job 4: small details + optional QR + feed + cut
        small_wrapped = wrap_text(body_small, 32).split("\n") if body_small else []

        def _job4(p):
            for ln in small_wrapped:
                _escpos_text(p, ln, font_size="normal")
            if edit_url:
                try:
                    p.qr(edit_url, size=3)
                    p.text("\n")
                except Exception:
                    _escpos_text(p, edit_url, font_size="small")
            p.text("\n\n")
            try:
                p.cut()
            except Exception:
                pass

        _escpos_job(printer_name, _job4)

    except Exception as e:
        print("--- Print fallback (console) ---")
        print(f"Printer: {printer_name}")
        print(f"Error: {e}")
        print(f"{l_pat} {pid_display}")
        print(div)
        print(wrap_text(name_line, 16))
        if medium_text:
            print(wrap_text(medium_text, 32))
        print(div)
        print(wrap_text(body_big, 16))
        print(div)
        print(wrap_text(body_small, 32))
        if edit_url:
            print(edit_url)
        print("(end)")