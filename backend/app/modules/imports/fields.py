"""The fields a merchant can import, with the header spellings we recognise for each.

One table drives both the automatic column matching and the template generator, so the two
cannot disagree about what a column is called. Synonyms are matched after ``normalize_header``
(case, spaces, punctuation and Arabic diacritics/letter variants removed).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FieldSpec:
    key: str
    label_ar: str
    label_en: str
    synonyms: tuple[str, ...]
    required: bool = False


# Sheet names are part of the template contract: Products / Variants / Opening Stock / Images.
SHEET_PRODUCTS = "Products"
SHEET_VARIANTS = "Variants"
SHEET_STOCK = "Opening Stock"
SHEET_IMAGES = "Images"
SHEET_CUSTOMERS = "Customers"

PRODUCT_FIELDS: tuple[FieldSpec, ...] = (
    # Optional here: a one-sheet file of names and prices is what most shops have, and the
    # validator derives the handle from the name (and refuses two names that collapse to one).
    # On the Variants sheet it stays required: a variant has to say which product it belongs to.
    FieldSpec(
        "product_ref",
        "معرّف المنتج",
        "Product ref",
        ("productref", "productid", "handle", "slug", "parentsku", "معرفالمنتج", "كودالمنتج"),
    ),
    FieldSpec(
        "title",
        "اسم المنتج",
        "Product name",
        ("title", "name", "productname", "producttitle", "اسمالمنتج", "الاسم", "المنتج", "الصنف"),
        required=True,
    ),
    FieldSpec(
        "category", "التصنيف", "Category", ("category", "type", "producttype", "التصنيف", "القسم")
    ),
    FieldSpec("brand", "الماركة", "Brand", ("brand", "vendor", "الماركة", "العلامةالتجارية")),
    FieldSpec(
        "description", "الوصف", "Description", ("description", "body", "details", "الوصف", "تفاصيل")
    ),
    FieldSpec("status", "الحالة", "Status", ("status", "state", "الحالة")),
)

VARIANT_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "product_ref",
        "معرّف المنتج",
        "Product ref",
        ("productref", "productid", "handle", "slug", "parentsku", "معرفالمنتج", "كودالمنتج"),
        required=True,
    ),
    FieldSpec("sku", "SKU", "SKU", ("sku", "itemcode", "code", "كود", "كودالصنف", "رمزالصنف")),
    FieldSpec(
        "barcode",
        "الباركود",
        "Barcode",
        ("barcode", "ean", "upc", "gtin", "ean13", "الباركود", "باركود"),
    ),
    FieldSpec("color", "اللون", "Color", ("color", "colour", "اللون", "لون")),
    FieldSpec("size", "المقاس", "Size", ("size", "المقاس", "مقاس", "الحجم")),
    FieldSpec(
        "price",
        "سعر البيع",
        "Price",
        ("price", "saleprice", "sellingprice", "retailprice", "سعرالبيع", "السعر", "سعر"),
        required=True,
    ),
    FieldSpec(
        "cost",
        "التكلفة",
        "Cost",
        ("cost", "costprice", "purchaseprice", "التكلفة", "سعرالشراء", "سعرالتكلفة"),
    ),
)

STOCK_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("sku", "SKU", "SKU", ("sku", "itemcode", "code", "كود", "كودالصنف"), required=True),
    FieldSpec("barcode", "الباركود", "Barcode", ("barcode", "ean", "الباركود", "باركود")),
    FieldSpec(
        "warehouse",
        "المخزن",
        "Warehouse",
        ("warehouse", "location", "store", "branch", "المخزن", "الفرع", "المستودع"),
    ),
    FieldSpec(
        "quantity",
        "الكمية",
        "Quantity",
        ("quantity", "qty", "stock", "onhand", "الكمية", "كمية", "الرصيد"),
        required=True,
    ),
)

CUSTOMER_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "name",
        "اسم العميل",
        "Customer name",
        ("name", "customername", "fullname", "customer", "client", "اسمالعميل", "الاسم", "العميل"),
        required=True,
    ),
    # Phone and email are each optional, but a row needs at least one: a name alone cannot be
    # told apart from the next customer with the same name, so it could never be matched again.
    FieldSpec(
        "phone",
        "الهاتف",
        "Phone",
        (
            "phone",
            "mobile",
            "tel",
            "telephone",
            "whatsapp",
            "phonenumber",
            "mobilenumber",
            "الهاتف",
            "رقمالهاتف",
            "الموبايل",
            "رقمالموبايل",
            "الجوال",
            "التليفون",
            "واتساب",
        ),
    ),
    FieldSpec(
        "email",
        "البريد الإلكتروني",
        "Email",
        ("email", "mail", "emailaddress", "البريد", "البريدالالكتروني", "الايميل", "ايميل"),
    ),
    FieldSpec(
        "source",
        "المصدر",
        "Source",
        ("source", "channel", "origin", "المصدر", "القناة"),
    ),
    FieldSpec("tags", "الوسوم", "Tags", ("tags", "tag", "labels", "الوسوم", "الوسم", "تصنيف")),
)

IMAGE_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("sku", "SKU", "SKU", ("sku", "itemcode", "code", "كود"), required=True),
    FieldSpec(
        "file_name",
        "رابط الصورة",
        "Image link",
        (
            "image",
            "imagelink",
            "imageurl",
            "url",
            "link",
            "photo",
            "picture",
            "imagefile",
            "filename",
            "file",
            "الصورة",
            "رابطالصورة",
            "اسمالصورة",
            "صورة",
        ),
        required=True,
    ),
)

SHEET_FIELDS: dict[str, tuple[FieldSpec, ...]] = {
    SHEET_PRODUCTS: PRODUCT_FIELDS,
    SHEET_VARIANTS: VARIANT_FIELDS,
    SHEET_STOCK: STOCK_FIELDS,
    SHEET_IMAGES: IMAGE_FIELDS,
    SHEET_CUSTOMERS: CUSTOMER_FIELDS,
}
