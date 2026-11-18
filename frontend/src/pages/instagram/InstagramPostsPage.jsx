import React from "react";
import { useNavigate, useParams } from "react-router-dom";
import InstagramCommentsPage from "./InstagramCommentsPage";

/** /instagram/posts and /instagram/posts/:postId — one post open at a time; the address follows the selection. */
export default function InstagramPostsPage() {
  const { postId } = useParams();
  const navigate = useNavigate();
  return <InstagramCommentsPage initialPostId={postId || null} onSelectPost={(id) => navigate(`/instagram/posts/${encodeURIComponent(id)}`, { replace: true })} />;
}
