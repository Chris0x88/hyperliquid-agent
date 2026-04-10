/** Design tokens from DESIGN.md */
export const theme = {
  colors: {
    primary: "#A26B32",
    primaryLight: "rgba(162, 107, 50, 0.15)",
    primaryBorder: "rgba(162, 107, 50, 0.3)",
    secondary: "#8F7156",
    secondaryLight: "rgba(143, 113, 86, 0.15)",
    tertiary: "#87CAE6",
    tertiaryLight: "rgba(135, 202, 230, 0.15)",
    tertiaryBorder: "rgba(135, 202, 230, 0.3)",
    neutral: "#7E756F",
    neutralLight: "rgba(126, 117, 111, 0.15)",

    bg: "#0d0e11",
    surface: "#1f2029",
    surfaceHover: "#1a1b22",
    border: "#353849",
    borderLight: "#1e1f26",

    text: "#f3f4f6",
    textSecondary: "#9ca3af",
    textMuted: "#7E756F",
    textDim: "#4f5666",

    success: "#22c55e",
    successLight: "rgba(34, 197, 94, 0.12)",
    successBorder: "rgba(34, 197, 94, 0.25)",
    danger: "#ef4444",
    dangerLight: "rgba(239, 68, 68, 0.12)",
    dangerBorder: "rgba(239, 68, 68, 0.25)",
    warning: "#f89b4b",
    warningLight: "rgba(248, 155, 75, 0.12)",
    warningBorder: "rgba(248, 155, 75, 0.25)",
  },
  fonts: {
    heading: "'Space Grotesk', system-ui, sans-serif",
    body: "'Inter', system-ui, sans-serif",
    mono: "var(--font-geist-mono), 'JetBrains Mono', monospace",
  },
  radius: "8px",
} as const;
