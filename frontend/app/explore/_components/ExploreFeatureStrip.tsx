import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { SHELL, featureStrip } from "../_lib/explore-data";

export function ExploreFeatureStrip() {
  return (
    <section className={cn(SHELL, "pt-10 pb-14")}>
      <Card className="grid grid-cols-1 gap-x-8 gap-y-7 rounded-3xl border-slate-200/80 bg-white/70 p-8 backdrop-blur sm:grid-cols-2 lg:grid-cols-4">
        {featureStrip.map((item) => (
          <div key={item.title} className="flex items-start gap-3.5">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-violet-100 bg-violet-50 text-violet-600">
              <item.icon className="size-5" />
            </div>
            <div>
              <strong className="block text-sm font-bold text-slate-900">{item.title}</strong>
              <p className="mt-1 text-xs leading-relaxed text-slate-500">{item.detail}</p>
            </div>
          </div>
        ))}
      </Card>
    </section>
  );
}
