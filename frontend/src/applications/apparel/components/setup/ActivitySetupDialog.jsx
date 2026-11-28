import React, { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  completeBody,
  isSelectable,
  presetCount,
  presetFor,
  sectorCards,
} from "@/applications/apparel/lib/activitySetup";
import { useCompleteActivitySetup, useSkipActivitySetup } from "@/applications/apparel/api/useActivitySetup";

/**
 * "What kind of shop is this?" Asked once, to a new owner. It sits over the app and never replaces
 * it: closing it (Esc, outside click, the skip button) is a skip, and the skip is on every step.
 * Only clothing and general can be picked; the other sectors are shown as coming soon and do
 * nothing when pressed.
 */
export default function ActivitySetupDialog({ open, setup, onClose, onDone }) {
  const [step, setStep] = useState(1);
  const [choice, setChoice] = useState(null);
  // On by default: the owner is told exactly what it sets and can turn it off. It is sent only if left on.
  const [applyPreset, setApplyPreset] = useState(true);
  const complete = useCompleteActivitySetup();
  const skip = useSkipActivitySetup();
  const busy = complete.isPending || skip.isPending;
  const cards = sectorCards(setup);
  const count = choice ? presetCount(setup, choice) : 0;
  const hasPreset = choice ? presetFor(setup, choice) !== null : false;

  const doSkip = () => {
    if (busy) return;
    skip.mutate(undefined, { onSuccess: () => onClose?.(), onError: () => onClose?.() });
  };

  const doComplete = () => {
    const body = completeBody(setup, choice, applyPreset);
    if (!body || busy) return;
    complete.mutate(body, { onSuccess: () => setStep(3) });
  };

  const pick = (id) => {
    if (!isSelectable(setup, id)) return;
    setChoice(id);
  };

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) (step === 3 ? onDone?.() : doSkip()); }}>
      <DialogContent className="max-w-lg" dir="rtl" data-testid="activity-setup">
        {step === 1 && (
          <>
            <DialogHeader>
              <DialogTitle>إيه نوع نشاطك؟</DialogTitle>
              <DialogDescription>
                هنجهّز لك النظام على قد نشاطك. تقدر تغيّر أي حاجة بعدين من الإعدادات.
              </DialogDescription>
            </DialogHeader>
            <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="نوع النشاط">
              {cards.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  role="radio"
                  aria-checked={choice === c.id}
                  aria-disabled={c.disabled}
                  disabled={c.disabled}
                  data-sector={c.id}
                  onClick={() => pick(c.id)}
                  className={
                    "rounded-lg border p-3 text-start transition " +
                    (c.disabled
                      ? "cursor-not-allowed opacity-50"
                      : choice === c.id
                        ? "border-primary bg-primary/5"
                        : "hover:bg-surface")
                  }
                >
                  <div className="font-medium">{c.label}</div>
                  <div className="text-xs text-muted-foreground">{c.hint}</div>
                </button>
              ))}
            </div>
            <DialogFooter className="gap-2 sm:justify-between">
              <Button type="button" variant="ghost" onClick={doSkip} disabled={busy}>
                تخطّي دلوقتي
              </Button>
              <Button type="button" onClick={() => setStep(2)} disabled={!choice || busy}>
                التالي
              </Button>
            </DialogFooter>
          </>
        )}

        {step === 2 && (
          <>
            <DialogHeader>
              <DialogTitle>{choice === "apparel" ? "إعدادات محل الملابس" : "نشاط عام"}</DialogTitle>
              <DialogDescription>
                {hasPreset
                  ? `سنضبط ${count} إعداداً جاهزاً لمتجر ملابس: كاشير بالنقدية، دون بيع آجل، ومصفوفة مقاس ولون، وإخفاء شاشات التحويلات والبيع أونلاين. ولن نغيّر أي إعداد ضبطته سابقاً.`
                  : "لا توجد إعدادات جاهزة لنشاط عام. ستضبط كل شيء بنفسك من الإعدادات."}
              </DialogDescription>
            </DialogHeader>
            {hasPreset && (
              <div className="flex items-center gap-2">
                <Checkbox
                  id="apply-preset"
                  checked={applyPreset}
                  onCheckedChange={(v) => setApplyPreset(v === true)}
                  disabled={busy}
                />
                <Label htmlFor="apply-preset">طبّق الإعدادات دي</Label>
              </div>
            )}
            {complete.isError && (
              <div role="alert" className="text-sm text-destructive">
                معرفناش نحفظ. جرّب تاني أو اتخطّى وكمّل شغلك.
              </div>
            )}
            <DialogFooter className="gap-2 sm:justify-between">
              <Button type="button" variant="ghost" onClick={doSkip} disabled={busy}>
                تخطّي دلوقتي
              </Button>
              <div className="flex gap-2">
                <Button type="button" variant="outline" onClick={() => setStep(1)} disabled={busy}>
                  رجوع
                </Button>
                <Button type="button" onClick={doComplete} disabled={busy}>
                  {busy ? "بنحفظ..." : "تمام"}
                </Button>
              </div>
            </DialogFooter>
          </>
        )}

        {step === 3 && (
          <>
            <DialogHeader>
              <DialogTitle>جاهز</DialogTitle>
              <DialogDescription>
                النظام اتجهّز. تقدر تعدّل أي إعداد من الإعدادات في أي وقت.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button type="button" onClick={() => onDone?.()}>
                ابدأ البيع
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
