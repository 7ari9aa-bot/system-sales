// صور شبكة بطاقات المخزون: النموذج بلا صور حقيقية للمنتجات، فنوزّع الصور المتوفرة بثبات على المنتجات.
const IMAGES = [
  "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/0bfefb89c_generated_b84d32d6.jpg",
  "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/6248bf927_generated_24562c66.jpg",
  "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/dd5f6d09b_generated_6a5b4424.jpg",
];

export const PRODUCT_IMAGES = IMAGES;

// اختيار صورة ثابتة لكل منتج حسب معرّفه.
export function productImage(key) {
  const text = String(key ?? "");
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) hash = (hash * 31 + text.charCodeAt(i)) % 9973;
  return IMAGES[hash % IMAGES.length];
}