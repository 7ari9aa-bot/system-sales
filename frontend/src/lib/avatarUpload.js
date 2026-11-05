/** One place decides what a failed avatar write tells the merchant.
 * The server's own message is never shown: it can carry storage internals. */

export const AVATAR_MAX_BYTES = 5 * 1024 * 1024;
const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);

export function isAcceptedImage(file) {
  return Boolean(file) && IMAGE_TYPES.has(file.type) && file.size <= AVATAR_MAX_BYTES;
}

export function avatarErrorKey(error) {
  if (error?.status === 413) return "avatar.tooLarge";
  if (error?.status === 415 || error?.code === "unsupported_media_type") return "avatar.notImage";
  if (error?.status === 401 || error?.status === 403) return "avatar.forbidden";
  if (error?.retryable) return "avatar.retry";
  return "avatar.failed";
}
