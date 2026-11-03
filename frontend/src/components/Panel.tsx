import { useId, type ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';

type PanelProps = {
  title: string;
  /** Short mono code shown next to the title, e.g. "DIAG-0x01". */
  code?: string;
  icon?: LucideIcon;
  accent?: string;
  /** Right-aligned slot in the title bar (filters, counts, badges). */
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  glow?: boolean;
};

/** Chamfered HUD container. Always a labelled `<section>` with an `<h2>`. */
export default function Panel({
  title,
  code,
  icon: Icon,
  accent = '#3f3f46',
  action,
  children,
  className = '',
  bodyClassName = '',
  glow = false,
}: PanelProps) {
  const headingId = useId();

  return (
    <section aria-labelledby={headingId} className={className}>
      <div className="relative">
        {glow && (
          <div
            aria-hidden="true"
            className="chamfer absolute -inset-[3px]"
            style={{ background: accent, filter: 'blur(13px)', opacity: 0.24 }}
          />
        )}
        <div className="chamfer relative p-px" style={{ background: accent }}>
          <div className="chamfer-sm bg-panel">
            <div className="flex items-center justify-between gap-3 border-b border-zinc-800 px-3 py-2">
              <div className="flex min-w-0 items-center gap-2">
                {Icon && <Icon size={13} style={{ color: accent }} className="shrink-0" aria-hidden="true" />}
                <h2
                  id={headingId}
                  className="truncate font-display text-[13px] font-bold uppercase tracking-[0.18em] text-zinc-50"
                >
                  {title}
                </h2>
                {code && <span className="font-mono text-[10px] text-zinc-400">{code}</span>}
              </div>
              {action}
            </div>
            <div className={`p-3 ${bodyClassName}`}>{children}</div>
          </div>
        </div>
      </div>
    </section>
  );
}
