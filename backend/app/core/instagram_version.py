"""The one Graph API version every Instagram call uses.

Lives in `core` (not in a module) so the message adapter and the connection verifier can both
read it without importing each other. Raise it here and nowhere else.
"""

INSTAGRAM_API_VERSION = "v27.0"
