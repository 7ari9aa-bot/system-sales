import React from "react";

/**
 * The owner ticked several Pages in Meta's dialog, but a channel holds one. Nothing is stored yet:
 * this asks which. No Page is pre-selected, so the first one is never taken without a choice.
 * Only each Page's id and name reach the browser; the tokens stay on the server.
 */
export default function MetaPageChoiceDialog({ choice, isAr, busy = false, error = "", onChoose, onCancel }) {
  const [selected, setSelected] = React.useState("");
  const pages = choice?.pages ?? [];
  const channelName = choice?.provider === "instagram" ? "Instagram" : choice?.provider === "messenger" ? "Messenger" : "Facebook";
  const title = isAr ? `اختر الصفحة التي تريد ربطها بـ ${channelName}` : `Choose the Page to connect to ${channelName}`;

  function submit(event) {
    event.preventDefault();
    if (selected && !busy) onChoose(selected);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" data-testid="meta-page-choice">
      <form
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onSubmit={submit}
        className="w-full max-w-md rounded-2xl bg-white p-5 shadow-xl"
        dir={isAr ? "rtl" : "ltr"}
      >
        <h2 className="text-[15px] font-semibold text-slate-900">{title}</h2>
        <p className="mt-1 text-[12.5px] text-slate-500">
          {isAr
            ? "اخترت أكثر من صفحة في نافذة فيسبوك، لكن القناة الواحدة تربط صفحة واحدة. يمكنك ربط غيرها لاحقًا."
            : "You picked more than one Page in Facebook's window, but a channel connects one Page. You can connect another later."}
        </p>

        <fieldset className="mt-3 space-y-2" disabled={busy}>
          <legend className="sr-only">{title}</legend>
          {pages.map((page) => (
            <label
              key={page.id}
              className={`flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-2.5 text-[13.5px] ${
                selected === page.id ? "border-emerald-500 bg-emerald-50" : "border-slate-200 hover:bg-slate-50"
              }`}
            >
              <input
                type="radio"
                name="meta-page"
                value={page.id}
                checked={selected === page.id}
                onChange={() => setSelected(page.id)}
              />
              <span className="font-medium text-slate-800">{page.name}</span>
            </label>
          ))}
        </fieldset>

        {error ? (
          <p role="alert" className="mt-3 text-[12.5px] text-red-600">
            {error}
          </p>
        ) : null}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="h-9 rounded-lg px-3.5 text-[13px] font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-60"
          >
            {isAr ? "إلغاء" : "Cancel"}
          </button>
          <button
            type="submit"
            disabled={!selected || busy}
            className="h-9 rounded-lg bg-emerald-600 px-4 text-[13px] font-semibold text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {busy ? (isAr ? "جارٍ الربط…" : "Connecting…") : isAr ? "ربط هذه الصفحة" : "Connect this Page"}
          </button>
        </div>
      </form>
    </div>
  );
}
