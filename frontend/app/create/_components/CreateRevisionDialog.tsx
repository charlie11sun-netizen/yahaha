"use client";

import * as Dialog from "@radix-ui/react-dialog";
import {
  ArrowLeft,
  Boxes,
  Bug,
  Check,
  Gamepad2,
  Gauge,
  Loader2,
  Palette,
  ShieldCheck,
  Sparkles,
  WandSparkles,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { Task } from "@/lib/types";

type RevisionFocus = "gameplay" | "visuals" | "difficulty" | "content" | "bug";
type RevisionPriority = "normal" | "high";

const focusOptions: Array<{
  value: RevisionFocus;
  label: string;
  icon: typeof Gamepad2;
}> = [
  { value: "gameplay", label: "Gameplay & controls", icon: Gamepad2 },
  { value: "visuals", label: "Visual style", icon: Palette },
  { value: "difficulty", label: "Difficulty & balance", icon: Gauge },
  { value: "content", label: "Content & progression", icon: Boxes },
  { value: "bug", label: "Bug or issue", icon: Bug },
];

export function CreateRevisionDialog({
  onOpenChange,
  onSubmit,
  open,
  revising,
  task,
}: {
  onOpenChange: (open: boolean) => void;
  onSubmit: (feedback: string) => Promise<boolean>;
  open: boolean;
  revising: boolean;
  task: Task;
}) {
  const [step, setStep] = useState<1 | 2>(1);
  const [focus, setFocus] = useState<RevisionFocus>("gameplay");
  const [outcome, setOutcome] = useState("");
  const [keepUnchanged, setKeepUnchanged] = useState("");
  const [priority, setPriority] = useState<RevisionPriority>("normal");

  useEffect(() => {
    setStep(1);
    setFocus("gameplay");
    setOutcome("");
    setKeepUnchanged("");
    setPriority("normal");
  }, [task.id]);

  const selectedFocus = useMemo(
    () => focusOptions.find((option) => option.value === focus) ?? focusOptions[0],
    [focus],
  );
  const previewSrc = task.game?.bundle_url || task.preview_url || (task.game ? `/play/${task.game.id}` : "");
  const canReview = outcome.trim().length > 0;

  const handleOpenChange = (nextOpen: boolean) => {
    if (revising && !nextOpen) return;
    if (!nextOpen) setStep(1);
    onOpenChange(nextOpen);
  };

  const submitRevision = async () => {
    if (!canReview || revising) return;
    const feedback = [
      `Revision focus: ${selectedFocus.label}`,
      `Desired outcome: ${outcome.trim()}`,
      keepUnchanged.trim() ? `Keep unchanged: ${keepUnchanged.trim()}` : "Keep unchanged: No additional constraints provided.",
      `Priority: ${priority === "high" ? "High" : "Normal"}`,
    ].join("\n\n");
    const started = await onSubmit(feedback);
    if (started) handleOpenChange(false);
  };

  return (
    <Dialog.Root onOpenChange={handleOpenChange} open={open}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/45 backdrop-blur-[1px] data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:fade-out data-[state=open]:fade-in" />
        <Dialog.Content
          aria-describedby="revision-dialog-description"
          className="fixed left-1/2 top-1/2 z-50 flex max-h-[calc(100vh-2rem)] w-[calc(100vw-2rem)] max-w-[1120px] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-2xl border border-white/70 bg-white shadow-[0_28px_90px_rgba(15,23,42,0.28)] outline-none data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:fade-out data-[state=open]:fade-in data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95"
        >
          <div className="shrink-0 px-6 pb-4 pt-6 sm:px-9 sm:pt-8">
            <div className="flex items-start gap-4">
              <span className="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600">
                <Sparkles size={22} />
              </span>
              <div className="min-w-0 flex-1">
                <Dialog.Title className="font-display text-2xl font-semibold tracking-tight text-slate-950">
                  Plan the next version
                </Dialog.Title>
                <Dialog.Description className="mt-1 text-sm text-slate-500" id="revision-dialog-description">
                  Choose a focus, then describe the outcome you want.
                </Dialog.Description>
              </div>
              <Dialog.Close asChild>
                <Button aria-label="Close revision planner" className="-mr-2 -mt-2 rounded-full text-slate-500" size="icon" type="button" variant="ghost">
                  <X size={20} />
                </Button>
              </Dialog.Close>
            </div>

            <div aria-label={`Step ${step} of 2`} className="mx-auto mt-6 flex max-w-md items-center" role="group">
              <StepIndicator active={step === 1} complete={step === 2} label="Define change" number={1} />
              <span className="mx-4 h-px flex-1 bg-slate-200" />
              <StepIndicator active={step === 2} complete={false} label="Review & create" number={2} />
            </div>
          </div>

          <div className="mx-6 h-px shrink-0 bg-slate-200 sm:mx-9" />

          {step === 1 ? (
            <div className="grid min-h-0 flex-1 overflow-y-auto px-6 py-5 sm:px-9 lg:grid-cols-[minmax(280px,0.78fr)_minmax(0,1.22fr)] lg:overflow-hidden">
              <section className="pb-5 lg:min-h-0 lg:overflow-y-auto lg:border-r lg:border-slate-200 lg:pb-0 lg:pr-8" aria-labelledby="revision-focus-heading">
                <h2 className="font-display text-base font-semibold text-slate-950" id="revision-focus-heading">
                  Change focus
                </h2>
                <div className="mt-3 overflow-hidden rounded-xl border border-slate-200" role="radiogroup" aria-label="Change focus">
                  {focusOptions.map((option) => {
                    const Icon = option.icon;
                    const selected = focus === option.value;
                    return (
                      <button
                        aria-checked={selected}
                        className={cn(
                          "flex min-h-13 w-full items-center gap-3 border-b border-slate-200 px-4 py-3 text-left text-sm font-medium transition last:border-b-0 focus-visible:relative focus-visible:z-10",
                          selected ? "bg-indigo-50 text-indigo-700" : "bg-white text-slate-700 hover:bg-slate-50",
                        )}
                        key={option.value}
                        onClick={() => setFocus(option.value)}
                        role="radio"
                        type="button"
                      >
                        <Icon className={selected ? "text-indigo-600" : "text-slate-500"} size={18} />
                        <span className="flex-1">{option.label}</span>
                        <span
                          aria-hidden="true"
                          className={cn(
                            "flex size-5 items-center justify-center rounded-full border",
                            selected ? "border-indigo-500 bg-indigo-600 text-white" : "border-slate-300 bg-white",
                          )}
                        >
                          {selected ? <Check size={12} strokeWidth={3} /> : null}
                        </span>
                      </button>
                    );
                  })}
                </div>

                <CurrentVersion previewSrc={previewSrc} title={task.game?.title || "Current game"} />
              </section>

              <section className="pt-5 lg:min-h-0 lg:overflow-y-auto lg:pl-8 lg:pt-0" aria-labelledby="revision-outcome-heading">
                <h2 className="font-display text-base font-semibold text-slate-950" id="revision-outcome-heading">
                  Describe the outcome
                </h2>
                <p className="mt-1 text-sm text-slate-500">Focus on what the player should notice or feel.</p>

                <label className="sr-only" htmlFor="revision-outcome">Desired outcome</label>
                <textarea
                  className="mt-3 min-h-48 w-full resize-y rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm leading-6 text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-indigo-400 focus:ring-4 focus:ring-indigo-100"
                  id="revision-outcome"
                  maxLength={2000}
                  onChange={(event) => setOutcome(event.target.value)}
                  placeholder="The player should dodge immediately when Space is pressed, with a brighter trail and stronger impact feedback."
                  value={outcome}
                />

                <div className="mt-4 grid gap-4 sm:grid-cols-[minmax(0,1fr)_200px]">
                  <label className="grid gap-2 text-sm font-semibold text-slate-700" htmlFor="revision-keep">
                    Keep unchanged
                    <input
                      className="h-10 rounded-lg border border-slate-200 bg-white px-3 text-sm font-normal text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-indigo-400 focus:ring-4 focus:ring-indigo-100"
                      id="revision-keep"
                      maxLength={300}
                      onChange={(event) => setKeepUnchanged(event.target.value)}
                      placeholder="Level layout, enemy count..."
                      value={keepUnchanged}
                    />
                  </label>

                  <fieldset className="grid gap-2">
                    <legend className="text-sm font-semibold text-slate-700">Priority</legend>
                    <div className="grid h-10 grid-cols-2 overflow-hidden rounded-lg border border-slate-200" role="radiogroup" aria-label="Revision priority">
                      {(["normal", "high"] as RevisionPriority[]).map((value) => (
                        <button
                          aria-checked={priority === value}
                          className={cn(
                            "border-r border-slate-200 text-sm font-medium capitalize transition last:border-r-0",
                            priority === value ? "bg-indigo-50 text-indigo-700" : "bg-white text-slate-600 hover:bg-slate-50",
                          )}
                          key={value}
                          onClick={() => setPriority(value)}
                          role="radio"
                          type="button"
                        >
                          {value}
                        </button>
                      ))}
                    </div>
                  </fieldset>
                </div>

                <div className="mt-5 flex items-center gap-3 rounded-xl bg-indigo-50 px-4 py-3 text-sm text-slate-700">
                  <WandSparkles className="shrink-0 text-indigo-600" size={18} />
                  We&apos;ll use this brief to create Version 2.
                </div>
              </section>
            </div>
          ) : (
            <RevisionReview
              focusLabel={selectedFocus.label}
              keepUnchanged={keepUnchanged}
              outcome={outcome}
              previewSrc={previewSrc}
              priority={priority}
              title={task.game?.title || "Current game"}
            />
          )}

          <footer className="flex shrink-0 flex-col gap-4 border-t border-slate-200 px-6 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-9">
            <p className="inline-flex items-center gap-2 text-sm text-slate-500">
              <ShieldCheck className="text-emerald-600" size={18} />
              Version 1 stays playable
            </p>
            <div className="flex items-center justify-end gap-3">
              {step === 2 ? (
                <Button className="rounded-lg" disabled={revising} onClick={() => setStep(1)} type="button" variant="ghost">
                  <ArrowLeft size={16} />
                  Back
                </Button>
              ) : null}
              <Dialog.Close asChild>
                <Button className="rounded-lg" disabled={revising} type="button" variant="outline">Cancel</Button>
              </Dialog.Close>
              {step === 1 ? (
                <Button className="rounded-lg px-5" disabled={!canReview} onClick={() => setStep(2)} type="button">
                  Review revision
                </Button>
              ) : (
                <Button className="rounded-lg px-5" disabled={revising} onClick={submitRevision} type="button">
                  {revising ? <Loader2 className="animate-spin" size={16} /> : <WandSparkles size={16} />}
                  {revising ? "Starting revision..." : "Create revision"}
                </Button>
              )}
            </div>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function StepIndicator({ active, complete, label, number }: { active: boolean; complete: boolean; label: string; number: number }) {
  return (
    <span className={cn("flex items-center gap-2 text-sm font-medium", active || complete ? "text-indigo-600" : "text-slate-500")}>
      <span
        className={cn(
          "flex size-7 items-center justify-center rounded-full border text-xs font-bold",
          active ? "border-indigo-600 bg-indigo-600 text-white" : complete ? "border-indigo-200 bg-indigo-50 text-indigo-700" : "border-slate-300 bg-white",
        )}
      >
        {complete ? <Check size={14} strokeWidth={3} /> : number}
      </span>
      <span className="whitespace-nowrap">{label}</span>
    </span>
  );
}

function CurrentVersion({ previewSrc, title }: { previewSrc: string; title: string }) {
  return (
    <div className="mt-4 flex items-center gap-3 rounded-xl border border-slate-200 bg-white p-2.5">
      <div className="h-14 w-24 shrink-0 overflow-hidden rounded-lg bg-slate-950">
        {previewSrc ? (
          <iframe
            aria-hidden="true"
            className="pointer-events-none h-full w-full border-0 bg-slate-950"
            sandbox="allow-scripts"
            src={previewSrc}
            tabIndex={-1}
            title=""
          />
        ) : null}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold text-slate-800">{title}</p>
        <p className="mt-1 text-xs text-slate-500">Version 1 - <span className="text-emerald-600">Ready</span></p>
      </div>
      <span className="flex size-6 shrink-0 items-center justify-center rounded-full border border-emerald-200 bg-emerald-50 text-emerald-700">
        <Check size={13} strokeWidth={3} />
      </span>
    </div>
  );
}

function RevisionReview({
  focusLabel,
  keepUnchanged,
  outcome,
  previewSrc,
  priority,
  title,
}: {
  focusLabel: string;
  keepUnchanged: string;
  outcome: string;
  previewSrc: string;
  priority: RevisionPriority;
  title: string;
}) {
  return (
    <div className="grid min-h-0 flex-1 overflow-y-auto px-6 py-5 sm:px-9 lg:grid-cols-[minmax(280px,0.78fr)_minmax(0,1.22fr)] lg:overflow-hidden">
      <section className="pb-5 lg:border-r lg:border-slate-200 lg:pb-0 lg:pr-8">
        <h2 className="font-display text-base font-semibold text-slate-950">Current version</h2>
        <CurrentVersion previewSrc={previewSrc} title={title} />
        <div className="mt-5 rounded-xl bg-emerald-50 px-4 py-3 text-sm leading-6 text-emerald-800">
          <div className="flex items-center gap-2 font-semibold"><ShieldCheck size={18} /> Safe to revise</div>
          <p className="mt-1 text-emerald-700">This revision creates a new task and leaves Version 1 unchanged.</p>
        </div>
      </section>
      <section className="pt-5 lg:pl-8 lg:pt-0">
        <h2 className="font-display text-base font-semibold text-slate-950">Review your revision brief</h2>
        <p className="mt-1 text-sm text-slate-500">Confirm the direction before creating Version 2.</p>
        <dl className="mt-5 divide-y divide-slate-200 overflow-hidden rounded-xl border border-slate-200 bg-white">
          <ReviewRow label="Change focus" value={focusLabel} />
          <ReviewRow label="Desired outcome" value={outcome.trim()} />
          <ReviewRow label="Keep unchanged" value={keepUnchanged.trim() || "No additional constraints provided."} />
          <ReviewRow label="Priority" value={priority === "high" ? "High" : "Normal"} />
        </dl>
        <div className="mt-5 flex items-center gap-3 rounded-xl bg-indigo-50 px-4 py-3 text-sm text-slate-700">
          <WandSparkles className="shrink-0 text-indigo-600" size={18} />
          Ready to create Version 2 from this brief.
        </div>
      </section>
    </div>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-1 px-4 py-3 sm:grid-cols-[140px_1fr] sm:gap-4">
      <dt className="text-sm font-semibold text-slate-600">{label}</dt>
      <dd className="text-sm leading-6 text-slate-800">{value}</dd>
    </div>
  );
}
