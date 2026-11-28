"""ZATCA TLV (Tag-Length-Value) QR code encoder and decoder (Phase 1 & Phase 2).

Tags:
1: Seller's Name (Text)
2: Seller's VAT Registration Number (15 digits)
3: Time Stamp (ISO 8601: YYYY-MM-DDTHH:MM:SS)
4: Invoice Total with VAT (e.g. 230.00)
5: VAT Total (e.g. 30.00)
6: Invoice XML SHA-256 Hash (Base64 or raw digest)
7: ECDSA Digital Signature
8: ECDSA Public Key
9: Cryptographic Stamp Identifier (CSID) Certificate Signature
"""

from __future__ import annotations

import base64


def encode_zatca_tlv(tags: dict[int, str | bytes]) -> str:
    """Encode dictionary of tags {1: seller_name, 2: vat_number, ...} into Base64 TLV."""
    buffer = bytearray()
    for tag_num in sorted(tags.keys()):
        val = tags[tag_num]
        val_bytes = val.encode("utf-8") if isinstance(val, str) else bytes(val)
        length = len(val_bytes)

        buffer.append(tag_num)
        if length < 128:
            buffer.append(length)
        else:
            len_bytes = length.to_bytes((length.bit_length() + 7) // 8, byteorder="big")
            buffer.append(0x80 | len(len_bytes))
            buffer.extend(len_bytes)
        buffer.extend(val_bytes)

    return base64.b64encode(buffer).decode("ascii")


def decode_zatca_tlv(b64_string: str) -> dict[int, bytes]:
    """Decode Base64 ZATCA TLV string into {tag_num: value_bytes}."""
    raw = base64.b64decode(b64_string)
    result: dict[int, bytes] = {}
    i = 0
    total_len = len(raw)

    while i < total_len:
        tag = raw[i]
        i += 1
        if i >= total_len:
            break

        length_byte = raw[i]
        i += 1

        if length_byte < 128:
            length = length_byte
        else:
            num_len_bytes = length_byte & 0x7F
            length = int.from_bytes(raw[i : i + num_len_bytes], byteorder="big")
            i += num_len_bytes

        val = raw[i : i + length]
        i += length
        result[tag] = val

    return result
