"""
Functions to get data from an e-card via a smartcard reader
"""

def read_data() -> tuple[str, str, str, str, str]:
    """
    Returns dummy e-card data for testing purposes.
    Returns: (lastname, firstname, birthday, insurance, sex)
    """
    lastname = "Mustermann"
    firstname = "Max"
    birthday = "1990-01-01"
    insurance = "1234010190"
    sex = "Male"

    return (lastname, firstname, birthday, insurance, sex)

