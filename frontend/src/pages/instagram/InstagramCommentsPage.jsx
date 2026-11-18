import React from "react";
import InstagramPostsWorkspace from "@/components/inbox/InstagramPostsWorkspace";
import { useInbox } from "@/pages/inbox/InboxProvider";

/** /instagram/comments — comments on the shop's posts (live data, or the demo account's samples). */
export default function InstagramCommentsPage({ initialPostId = null, onSelectPost }) {
  const { demoAccount, instagramPosts, igLive, lang, addInstagramPageReply } = useInbox();
  if (demoAccount) return <InstagramPostsWorkspace posts={instagramPosts} lang={lang} onReply={addInstagramPageReply} initialPostId={initialPostId} onSelectPost={onSelectPost} />;
  return (
    <InstagramPostsWorkspace
      posts={igLive.posts}
      lang={lang}
      initialPostId={initialPostId}
      onSelectPost={onSelectPost}
      loading={igLive.loading}
      loadError={igLive.error}
      onRefresh={igLive.refresh}
      onPublish={igLive.publish}
      onReply={igLive.reply}
      onHide={igLive.hide}
      onDelete={igLive.remove}
      onPrivateReply={igLive.sendPrivate}
    />
  );
}
