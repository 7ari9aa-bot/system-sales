import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchPage } from "@/lib/facebookApi";
import { useInbox } from "@/pages/inbox/InboxProvider";
import { useFacebookPosts } from "@/hooks/useFacebookPosts";

/** True when a customer's comment still has no answer from the Page. */
export function needsAnswer(comment) {
  if (!comment || comment.isPage || comment.hidden) return false;
  if (comment.repliedAt || comment.privateRepliedAt) return false;
  return !(comment.replies || []).some((reply) => reply.isPage);
}

/** Everything the Facebook pages share: the Page itself, its posts and the comment actions. */
export function useFacebookData() {
  const inbox = useInbox();
  const { demoAccount, lang, convMap } = inbox;
  const enabled = !demoAccount;

  const page = useQuery({
    queryKey: ["facebook-page"],
    queryFn: fetchPage,
    enabled,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });
  const pageInfo = demoAccount ? { name: "Fihrist", about: "", picture: { data: { url: "/fihrist-mark.svg" } } } : page.data || null;
  const pageName = pageInfo?.name || "";
  const live = useFacebookPosts({ enabled, lang, pageName });

  const unanswered = useMemo(
    () => live.posts.reduce((sum, post) => sum + (post.comments || []).filter(needsAnswer).length, 0),
    [live.posts],
  );
  const threads = convMap.facebook || [];
  const unreadMessages = threads.reduce((sum, row) => sum + (row.unread > 0 || row.markedUnread ? 1 : 0), 0);

  return {
    ...inbox,
    page: pageInfo,
    pageName,
    pageAvatar: pageInfo?.picture?.data?.url || "",
    pageLoading: enabled && page.isLoading,
    pageError: enabled && page.error ? page.error.message || "error" : "",
    live,
    posts: live.posts,
    postsLoading: live.loading,
    postsError: live.error,
    unanswered,
    unreadMessages,
    canAct: enabled,
  };
}
