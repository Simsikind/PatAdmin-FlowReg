"""
Patient.py
Class for a Patient
"""

class Patient:
    # Empty string means "unspecified" (used for UI option None/Other)
    ALLOWED_SEX = {"Male", "Female", ""}
    ALLOWED_NACA = {"I", "II", "III", "IV", "V", "VI", "VII"}

    def __init__(
        self,
        firstname: str,
        lastname: str,
        group_id: int,
        group_name: str = "",
        external_id: str = "",
        naca: str = "I",
        sex: str = "Male",
        info: str = "",
        diagnosis: str = "",
        insurance: str = "",
        birthday: str = "",
    ):
        self.firstname = firstname
        self.lastname = lastname
        self.group_id = group_id
        self.group_name = group_name
        self.external_id = external_id

        if sex not in self.ALLOWED_SEX:
            raise ValueError(f"Invalid sex '{sex}'. Must be one of {sorted(self.ALLOWED_SEX)}")
        self.sex = sex

        if naca not in self.ALLOWED_NACA:
            raise ValueError(f"Invalid naca '{naca}'. Must be one of {sorted(self.ALLOWED_NACA)}")
        self.naca = naca

        self.info = info
        self.diagnosis = diagnosis
        self.insurance = insurance
        self.birthday = birthday  # YYYY-MM-DD

    def to_payload(self, add_new_flow: bool = False) -> dict:
        payload = {
            "firstname": self.firstname,
            "lastname": self.lastname,
            "group": self.group_id,
            "externalId": self.external_id,
            "naca": self.naca,
            "info": self.info,
            "diagnosis": self.diagnosis,
            "insurance": self.insurance,
            "birthday": self.birthday,
        }

        # Only include sex when it is explicitly set.
        if self.sex != "":
            payload["sex"] = self.sex
        if add_new_flow:
            payload["addNew"] = "true"
        return payload