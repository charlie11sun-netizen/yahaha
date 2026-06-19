import type { ReactElement, SVGProps } from "react";

export type IconComponent = (props: IconProps) => ReactElement;

type IconProps = SVGProps<SVGSVGElement> & {
  size?: number;
};

function base(size = 18, props: IconProps) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    ...props,
  };
}

export function ArrowRight({ size = 18, ...props }: IconProps) {
  return (
    <svg {...base(size, props)}>
      <path d="M5 12h14" />
      <path d="m13 6 6 6-6 6" />
    </svg>
  );
}

export function BadgeCheck({ size = 18, ...props }: IconProps) {
  return (
    <svg {...base(size, props)}>
      <circle cx="12" cy="12" r="9" />
      <path d="m8.5 12.5 2.3 2.3 4.9-5.6" />
    </svg>
  );
}

export function Calendar({ size = 18, ...props }: IconProps) {
  return (
    <svg {...base(size, props)}>
      <path d="M8 2v4" />
      <path d="M16 2v4" />
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M3 10h18" />
    </svg>
  );
}

export function CirclePlay({ size = 18, ...props }: IconProps) {
  return (
    <svg {...base(size, props)}>
      <circle cx="12" cy="12" r="9" />
      <path d="m10 8 6 4-6 4Z" />
    </svg>
  );
}

export function Database({ size = 18, ...props }: IconProps) {
  return (
    <svg {...base(size, props)}>
      <ellipse cx="12" cy="5" rx="8" ry="3" />
      <path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
      <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
    </svg>
  );
}

export function Gamepad2({ size = 18, ...props }: IconProps) {
  return (
    <svg {...base(size, props)}>
      <path d="M6 11h4" />
      <path d="M8 9v4" />
      <path d="M15 12h.01" />
      <path d="M18 10h.01" />
      <path d="M17.3 6H6.7A4.7 4.7 0 0 0 2 10.7v2.8a3.5 3.5 0 0 0 6.1 2.3L10 14h4l1.9 1.8a3.5 3.5 0 0 0 6.1-2.3v-2.8A4.7 4.7 0 0 0 17.3 6Z" />
    </svg>
  );
}

export function Globe2({ size = 18, ...props }: IconProps) {
  return (
    <svg {...base(size, props)}>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3a14 14 0 0 1 0 18" />
      <path d="M12 3a14 14 0 0 0 0 18" />
    </svg>
  );
}

export function Layers({ size = 18, ...props }: IconProps) {
  return (
    <svg {...base(size, props)}>
      <path d="m12 2 9 5-9 5-9-5 9-5Z" />
      <path d="m3 12 9 5 9-5" />
      <path d="m3 17 9 5 9-5" />
    </svg>
  );
}

export function ListChecks({ size = 18, ...props }: IconProps) {
  return (
    <svg {...base(size, props)}>
      <path d="m3 7 1.5 1.5L7 6" />
      <path d="m3 17 1.5 1.5L7 16" />
      <path d="M10 7h11" />
      <path d="M10 17h11" />
      <path d="M10 12h8" />
    </svg>
  );
}

export function MessageCircle({ size = 18, ...props }: IconProps) {
  return (
    <svg {...base(size, props)}>
      <path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 8.7 8.7 0 0 1-3.8-.9L3 21l1.8-4.8A8.3 8.3 0 1 1 21 11.5Z" />
    </svg>
  );
}

export function Play({ size = 18, ...props }: IconProps) {
  return (
    <svg {...base(size, props)} stroke="none" fill={props.fill ?? "currentColor"}>
      <path d="M7 4v16l13-8L7 4Z" />
    </svg>
  );
}

export function PlaySquare({ size = 18, ...props }: IconProps) {
  return (
    <svg {...base(size, props)}>
      <rect x="3" y="3" width="18" height="18" rx="3" />
      <path d="m10 8 6 4-6 4Z" />
    </svg>
  );
}

export function Search({ size = 18, ...props }: IconProps) {
  return (
    <svg {...base(size, props)}>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  );
}

export function Server({ size = 18, ...props }: IconProps) {
  return (
    <svg {...base(size, props)}>
      <rect x="3" y="4" width="18" height="7" rx="2" />
      <rect x="3" y="13" width="18" height="7" rx="2" />
      <path d="M7 7.5h.01" />
      <path d="M7 16.5h.01" />
    </svg>
  );
}

export function Sparkles({ size = 18, ...props }: IconProps) {
  return (
    <svg {...base(size, props)}>
      <path d="m12 3 1.7 4.3L18 9l-4.3 1.7L12 15l-1.7-4.3L6 9l4.3-1.7L12 3Z" />
      <path d="M19 14v4" />
      <path d="M21 16h-4" />
      <path d="M5 17v2" />
      <path d="M6 18H4" />
    </svg>
  );
}

export function UploadCloud({ size = 18, ...props }: IconProps) {
  return (
    <svg {...base(size, props)}>
      <path d="M16 16h1.5a4.5 4.5 0 0 0 .5-9 6 6 0 0 0-11.3-1.8A4.8 4.8 0 0 0 6 15.8h2" />
      <path d="m12 12-3 3" />
      <path d="m12 12 3 3" />
      <path d="M12 12v8" />
    </svg>
  );
}

export function WandSparkles({ size = 18, ...props }: IconProps) {
  return (
    <svg {...base(size, props)}>
      <path d="m15 4 5 5" />
      <path d="M4 20 17 7" />
      <path d="m13 6 5 5" />
      <path d="M6 4v3" />
      <path d="M7.5 5.5h-3" />
      <path d="M19 15v3" />
      <path d="M20.5 16.5h-3" />
    </svg>
  );
}

export function Box({ size = 18, ...props }: IconProps) {
  return (
    <svg {...base(size, props)}>
      <path d="m12 2 8 4.5v9L12 20l-8-4.5v-9L12 2Z" />
      <path d="M12 11 4.5 6.8" />
      <path d="m12 11 7.5-4.2" />
      <path d="M12 11v8.5" />
    </svg>
  );
}
