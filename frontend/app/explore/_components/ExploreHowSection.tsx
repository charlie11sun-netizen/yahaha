import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { SHELL, flowSteps } from "../_lib/explore-data";

export function ExploreHowSection() {
  return (
    <section id="how" className={cn(SHELL, "scroll-mt-20 pt-12 pb-6")}>
      <h2 className="font-display text-2xl font-bold tracking-tight text-slate-900">From idea to play</h2>
      <p className="mt-1 text-sm text-slate-500">Four steps, fully automated by a team of AI agents.</p>
      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {flowSteps.map((step, index) => (
          <Card
            key={step.title}
            className="group relative gap-0 overflow-hidden rounded-2xl border-slate-200/80 bg-white/80 p-5 backdrop-blur transition-all hover:-translate-y-1 hover:shadow-xl hover:shadow-slate-900/5"
          >
            <div className="flex items-center justify-between">
              <div className={cn("flex size-11 items-center justify-center rounded-xl bg-gradient-to-br text-white shadow-md", step.tint)}>
                <step.icon className="size-5" />
              </div>
              <span className="font-display text-3xl font-bold text-slate-200 transition-colors group-hover:text-slate-300">
                {String(index + 1).padStart(2, "0")}
              </span>
            </div>
            <h3 className="mt-4 font-display text-base font-bold text-slate-900">{step.title}</h3>
            <p className="mt-1.5 text-sm leading-relaxed text-slate-500">{step.detail}</p>
          </Card>
        ))}
      </div>
    </section>
  );
}
