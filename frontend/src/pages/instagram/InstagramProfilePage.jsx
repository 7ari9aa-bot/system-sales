import React from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import IgAvatar from "@/components/instagram/IgAvatar";
import InstagramPostView from "@/components/instagram/InstagramPostView";
import { IG, igCount } from "@/components/instagram/igTheme";
import { IgCarousel, IgComment, IgGrid, IgHeart, IgReels } from "@/components/instagram/igIcons";
import { cn } from "@/lib/utils";
import { useInstagramData } from "./useInstagramData";

function Stat({ value, label }) {
  if (value == null) return null;
  return <li className="text-[16px]"><span className="font-semibold">{value}</span> <span>{label}</span></li>;
}

function Tile({ post, lang }) {
  const isArabic = lang === "ar";
  return (
    <Link to={`/instagram/p/${encodeURIComponent(post.id)}`} state={{ fromProfile: true }} data-testid="ig-grid-tile" aria-label={post.text || (isArabic ? "منشور" : "Post")}
      className="group relative block aspect-[3/4] overflow-hidden bg-[#efefef]">
      {post.mediaUrl
        ? (post.mediaType === "video" && !/\.(jpe?g|png|webp)/i.test(post.mediaUrl)
          ? <video src={post.mediaUrl} muted playsInline preload="metadata" className="h-full w-full object-cover" />
          : <img src={post.mediaUrl} alt="" loading="lazy" className="h-full w-full object-cover" />)
        : <span dir="auto" className="grid h-full w-full place-items-center p-3 text-center text-[13px] text-[#737373]">{post.text}</span>}
      {post.mediaType === "video" && <span className="absolute end-2 top-2 text-white drop-shadow"><IgReels size={20} filled /></span>}
      {post.isCarousel && <span className="absolute end-2 top-2 text-white drop-shadow"><IgCarousel size={20} /></span>}
      <span className="absolute inset-0 hidden items-center justify-center gap-7 bg-black/30 text-[16px] font-bold text-white group-hover:flex">
        <span className="flex items-center gap-1.5"><IgHeart size={20} filled />{igCount(post.likes || 0, lang)}</span>
        <span className="flex items-center gap-1.5"><IgComment size={20} filled className="-scale-x-100" />{igCount(post.commentsCount || (post.comments || []).length, lang)}</span>
      </span>
    </Link>
  );
}

/** /instagram/profile, /instagram/profile/reels and /instagram/p/:postId (a post opened over the grid). */
export default function InstagramProfilePage({ tab = "posts" }) {
  const { lang, account, accountError, username, posts, postsLoading, postsError, actions, demoAccount } = useInstagramData();
  const { postId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const isArabic = lang === "ar";
  const shown = tab === "reels" ? posts.filter((p) => p.mediaType === "video" || p.isReel) : posts;
  const openIndex = postId ? posts.findIndex((p) => p.id === postId) : -1;
  const open = openIndex >= 0 ? posts[openIndex] : null;
  const close = () => (location.state?.fromProfile ? navigate(-1) : navigate("/instagram/profile"));
  const go = (index) => navigate(`/instagram/p/${encodeURIComponent(posts[index].id)}`, { replace: true, state: location.state });
  const tabClass = (active) => cn("flex h-[52px] items-center gap-1.5 border-t text-[12px] font-semibold uppercase tracking-[1px]", active ? "-mt-px border-black text-black" : "border-transparent text-[#737373]");

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[935px] px-5 pt-8">
        <header className="flex items-center gap-7 pb-10 md:gap-24 md:px-12">
          <IgAvatar src={account?.profile_picture_url} size={150} className="hidden md:inline-block" />
          <IgAvatar src={account?.profile_picture_url} size={77} className="md:hidden" />
          <section className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-3">
              <h1 dir="ltr" className="text-[20px] font-normal">{username || "Instagram"}</h1>
              {account?.username && <a href={`https://www.instagram.com/${encodeURIComponent(account.username)}/`} target="_blank" rel="noreferrer" className="rounded-lg px-4 py-[7px] text-[14px] font-semibold hover:bg-[#dbdbdb]" style={{ background: IG.button }}>{isArabic ? "فتح على إنستغرام" : "View on Instagram"}</a>}
              {actions.refresh && <button type="button" onClick={() => actions.refresh()} className="rounded-lg px-4 py-[7px] text-[14px] font-semibold hover:bg-[#dbdbdb]" style={{ background: IG.button }}>{isArabic ? "تحديث" : "Refresh"}</button>}
            </div>
            <ul className="mt-5 hidden gap-10 md:flex">
              <Stat value={igCount(account?.media_count ?? posts.length, lang)} label={isArabic ? "منشور" : "posts"} />
              <Stat value={igCount(account?.followers_count, lang)} label={isArabic ? "متابِع" : "followers"} />
              <Stat value={igCount(account?.follows_count, lang)} label={isArabic ? "يتابع" : "following"} />
            </ul>
            <div className="mt-5 text-[14px] leading-[18px]">
              {account?.name && <p className="font-semibold">{account.name}</p>}
              {account?.biography && <p dir="auto" className="whitespace-pre-line">{account.biography}</p>}
              {account?.website && <a href={account.website} target="_blank" rel="noreferrer" dir="ltr" className="font-semibold" style={{ color: IG.link }}>{account.website.replace(/^https?:\/\//, "")}</a>}
            </div>
            {accountError && <p role="alert" className="mt-3 text-[12px]" style={{ color: IG.error }}>{isArabic ? "تعذر تحميل بيانات الحساب من إنستغرام." : "Couldn't load the account from Instagram."}</p>}
          </section>
        </header>
        <ul className="flex justify-around border-t py-3 text-center md:hidden" style={{ borderColor: IG.border }}>
          {[[account?.media_count ?? posts.length, isArabic ? "منشور" : "posts"], [account?.followers_count, isArabic ? "متابِع" : "followers"], [account?.follows_count, isArabic ? "يتابع" : "following"]].map(([v, l]) => v == null ? null : <li key={l} className="text-[14px]" style={{ color: IG.secondary }}><span className="block font-semibold text-black">{igCount(v, lang)}</span>{l}</li>)}
        </ul>
        <nav aria-label={isArabic ? "أقسام الملف الشخصي" : "Profile tabs"} className="flex justify-center gap-14 border-t" style={{ borderColor: IG.border }}>
          <Link to="/instagram/profile" aria-current={tab === "posts" ? "page" : undefined} className={tabClass(tab === "posts")}><IgGrid size={12} />{isArabic ? "المنشورات" : "Posts"}</Link>
          <Link to="/instagram/profile/reels" aria-current={tab === "reels" ? "page" : undefined} className={tabClass(tab === "reels")}><IgReels size={12} />{isArabic ? "ريلز" : "Reels"}</Link>
        </nav>
        {postsError && <p role="alert" className="py-10 text-center text-[14px]" style={{ color: IG.error }}>{isArabic ? "تعذر تحميل المنشورات." : "Couldn't load posts."} {postsError}</p>}
        {postsLoading && shown.length === 0 && <p role="status" className="py-10 text-center text-[14px]" style={{ color: IG.secondary }}>{isArabic ? "جارٍ التحميل…" : "Loading…"}</p>}
        {!postsLoading && !postsError && shown.length === 0 && (
          <div className="py-16 text-center">
            <span className="mx-auto grid h-16 w-16 place-items-center rounded-full border-2 border-black">{tab === "reels" ? <IgReels size={32} /> : <IgGrid size={32} />}</span>
            <h2 className="mt-4 text-[30px] font-extrabold">{tab === "reels" ? (isArabic ? "لا توجد ريلز" : "No reels yet") : (isArabic ? "لا توجد منشورات بعد" : "No posts yet")}</h2>
            {!demoAccount && <p data-testid="ig-empty" className="mx-auto mt-3 max-w-md text-[14px] leading-[1.7]" style={{ color: IG.secondary }}>{isArabic ? "لا توجد منشورات بعد. لو ربطت الحساب قبل إضافة التعليقات، أعد ربط إنستغرام مرة واحدة لمنح الصلاحيات الجديدة." : "No posts yet. If you connected the account before comments were added, reconnect Instagram once to grant the new permissions."}</p>}
          </div>
        )}
        <div className="grid grid-cols-3 gap-[3px] pb-10">{shown.map((post) => <Tile key={post.id} post={post} lang={lang} />)}</div>
      </div>
      {postId && open && (
        <InstagramPostView post={open} lang={lang} actions={actions} onClose={close}
          onPrev={openIndex > 0 ? () => go(openIndex - 1) : undefined}
          onNext={openIndex < posts.length - 1 ? () => go(openIndex + 1) : undefined} />
      )}
      {postId && !open && !postsLoading && (
        <div role="alert" className="fixed inset-0 z-50 grid place-items-center bg-black/65" onClick={close}>
          <p className="rounded-xl bg-white px-6 py-5 text-[14px]">{isArabic ? "هذا المنشور غير متاح." : "This post isn't available."}</p>
        </div>
      )}
    </div>
  );
}
