import { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "danger" | "ghost";

const variants: Record<Variant, string> = {
  primary:
    "text-white shadow-sm",
  secondary:
    "border",
  danger:
    "text-white shadow-sm",
  ghost:
    "",
};

const variantStyles: Record<Variant, React.CSSProperties> = {
  primary: { backgroundColor: "var(--text)", color: "var(--bg)" },
  secondary: { backgroundColor: "var(--bg-subtle)", color: "var(--text)", borderColor: "var(--border)" },
  danger: { backgroundColor: "var(--danger)", color: "#fff" },
  ghost: { color: "var(--text-2)", backgroundColor: "transparent" },
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

export function Button({
  variant = "primary",
  className = "",
  style,
  disabled,
  ...props
}: ButtonProps) {
  return (
    <button
      className={`
        inline-flex items-center justify-center
        px-4 py-2 rounded-lg
        font-medium text-sm tracking-tight
        transition-all duration-150
        disabled:opacity-40 disabled:cursor-not-allowed
        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-1
        ${variants[variant]} ${className}
      `}
      style={{ ...variantStyles[variant], ...style }}
      disabled={disabled}
      {...props}
    />
  );
}
