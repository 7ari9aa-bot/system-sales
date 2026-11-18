import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useInbox } from "@/pages/inbox/InboxProvider";

/** True when a customer's comment still has no answer from the shop. */
export function needsAnswer(comment) {
  if (!comment || comment.isPage || comment.hidden) return false;
  if (comment.repliedAt || comment.privateRepliedAt) return false;
  return !(comment.replies || []).some((reply) => reply.isPage);
}

/** Everything the Instagram pages share: the shop's account, its posts and the comment actions. */
export function useInstagramData() {
  const inbox = useInbox();
  const { demoAccount, instagramPosts, igLive, addInstagramPageReply, convMap, lang } = inbox;

  const account = useQuery({
    queryKey: ["instagram-account"],
    queryFn: () => api("/social/account"),
    enabled: !demoAccount,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });

  const accountInfo = demoAccount
    ? { username: "fihrist.store", name: "Fihrist", profile_picture_url: "/fihrist-mark.svg", biography: lang === "ar" ? "متجر تجريبي" : "Demo shop" }
    : account.data || null;
  const username = accountInfo?.username || "";

  const posts = useMemo(() => {
    const list = demoAccount ? instagramPosts : igLive.posts;
    const name = (comment) => ({ ...(comment.isPage && username ? { ...comment, author: username, handle: username } : comment), replies: (comment.replies || []).map(name) });
    return (list || []).map((post) => ({
      ...post,
      comments: (post.comments || []).map(name),
      accountName: post.accountName || username,
      accountAvatarUrl: post.accountAvatarUrl || accountInfo?.profile_picture_url || "",
    }));
  }, [demoAccount, instagramPosts, igLive.posts, username, accountInfo?.profile_picture_url]);

  const actions = demoAccount
    ? { reply: addInstagramPageReply, canComment: true }
    : { reply: igLive.reply, hide: igLive.hide, remove: igLive.remove, sendPrivate: igLive.sendPrivate, publish: igLive.publish, refresh: igLive.refresh, canComment: false };

  const threads = convMap.instagram || [];
  const unreadMessages = threads.reduce((sum, row) => sum + (row.unread > 0 || row.markedUnread ? 1 : 0), 0);
  const unanswered = posts.reduce((sum, post) => sum + (post.comments || []).filter(needsAnswer).length, 0);

  return {
    ...inbox,
    account: accountInfo,
    accountLoading: !demoAccount && account.isLoading,
    accountError: !demoAccount && account.error ? account.error.message || "error" : "",
    username,
    posts,
    postsLoading: !demoAccount && igLive.loading,
    postsError: !demoAccount ? igLive.error : "",
    actions,
    threads,
    unreadMessages,
    unanswered,
  };
}
