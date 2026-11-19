import React from "react";

/** Permissions Facebook has not granted this connection. Chat keeps working without them; posting,
 *  comment moderation and insights do not, so the owner is asked to connect again. */
export function facebookNeedsRelink(channel) {
  return channel?.id === "facebook" && channel.connected === true && (channel.missingScopes?.length ?? 0) > 0;
}

export default function FacebookRelinkNotice({ channel, isAr }) {
  if (!facebookNeedsRelink(channel)) return null;
  const list = channel.missingScopes.join(isAr ? "، " : ", ");
  return (
    <div role="alert" data-testid="facebook-relink-notice" className="mt-1 text-[11.5px] text-amber-700">
      {isAr
        ? `الشات يعمل، لكن النشر والتعليقات والإحصاءات تحتاج صلاحيات إضافية من فيسبوك (${list}). اضغط «إعادة ربط» ووافق على كل الصلاحيات.`
        : `Chat works, but posting, comments and insights need more permissions from Facebook (${list}). Press Reconnect and allow all of them.`}
    </div>
  );
}
