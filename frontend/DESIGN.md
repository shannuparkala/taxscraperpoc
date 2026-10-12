---
name: TaxPulse AI
colors:
  surface: '#0b1326'
  surface-dim: '#0b1326'
  surface-bright: '#31394d'
  surface-container-lowest: '#060e20'
  surface-container-low: '#131b2e'
  surface-container: '#171f33'
  surface-container-high: '#222a3d'
  surface-container-highest: '#2d3449'
  on-surface: '#dae2fd'
  on-surface-variant: '#bbcabf'
  inverse-surface: '#dae2fd'
  inverse-on-surface: '#283044'
  outline: '#86948a'
  outline-variant: '#3c4a42'
  surface-tint: '#4edea3'
  primary: '#4edea3'
  on-primary: '#003824'
  primary-container: '#10b981'
  on-primary-container: '#00422b'
  inverse-primary: '#006c49'
  secondary: '#4cd7f6'
  on-secondary: '#003640'
  secondary-container: '#03b5d3'
  on-secondary-container: '#00424e'
  tertiary: '#ffb95f'
  on-tertiary: '#472a00'
  tertiary-container: '#e29100'
  on-tertiary-container: '#523200'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#6ffbbe'
  primary-fixed-dim: '#4edea3'
  on-primary-fixed: '#002113'
  on-primary-fixed-variant: '#005236'
  secondary-fixed: '#acedff'
  secondary-fixed-dim: '#4cd7f6'
  on-secondary-fixed: '#001f26'
  on-secondary-fixed-variant: '#004e5c'
  tertiary-fixed: '#ffddb8'
  tertiary-fixed-dim: '#ffb95f'
  on-tertiary-fixed: '#2a1700'
  on-tertiary-fixed-variant: '#653e00'
  background: '#0b1326'
  on-background: '#dae2fd'
  surface-variant: '#2d3449'
typography:
  headline-xl:
    fontFamily: Inter
    fontSize: 40px
    fontWeight: '700'
    lineHeight: 48px
    letterSpacing: -0.03em
  headline-xl-mobile:
    fontFamily: Inter
    fontSize: 30px
    fontWeight: '700'
    lineHeight: 38px
    letterSpacing: -0.025em
  headline-lg:
    fontFamily: Inter
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
    letterSpacing: -0.02em
  headline-lg-mobile:
    fontFamily: Inter
    fontSize: 22px
    fontWeight: '600'
    lineHeight: 30px
    letterSpacing: -0.015em
  headline-md:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 26px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22px
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
  label-lg:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
    letterSpacing: -0.01em
  label-md:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.02em
  label-sm:
    fontFamily: JetBrains Mono
    fontSize: 10px
    fontWeight: '600'
    lineHeight: 14px
    letterSpacing: 0.05em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-mobile: 0.75rem
  margin: 1.5rem
  margin-mobile: 1rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2rem
---

## Brand & Style

This design system embodies an AI-first executive fintech ethos: authoritative, surgical, and effortlessly high-velocity. Tailored for executive tax strategists, CPAs, and high-growth founders operating on mobile devices, it strips away enterprise clutter in favor of high-signal clarity.

The visual style blends **Obsidian Deep Dark Minimalism** with **Precision Glassmorphism**:
- **Obsidian Dark Foundation**: Anchored in pitch and deep slate obsidian tones to reduce ocular strain during intensive crunch periods and spotlight complex numbers cleanly.
- **Luminous Chromatic Accents**: High-potency emerald and mint indicators communicate positive variance, operational confidence, and AI computational verification. Urgent amber highlights provide critical awareness for statutory tax deadlines and filing cut-offs.
- **Glassmorphic Precision**: High-frequency surfaces feature micro-translucent 1px boundaries, subtle linear gradient bevels, and atmospheric background glow nodes that signify real-time AI background processing.

## Colors

The palette leverages an obsidian spectrum designed for deep contrast and focused readability under varying ambient lighting.

- **Primary (`#10B981` / Emerald Mint)**: Denotes completed actions, verified tax positions, synthetic AI reasoning status, and positive net impact. Supported by `#059669` for active/pressed states and `#34D399` for hover/glow highlights.
- **Secondary (`#06B6D4` / Electric Cyan)**: Reserved for conversational prompts, contextual intelligence, interactive code/stat widgets, and system-level telemetry.
- **Tertiary (`#F59E0B` / Urgent Amber)**: Used strictly for deadline countdowns, IRS notices, pending compliance events, and temporal countdown thresholds under 7 days.
- **Neutral Core**:
  - Canvas Base: `#080C14`
  - Elevated Container / Cards: `#0F172A`
  - Sub-surface / Inset Wells: `#0B1120`
  - Structural Ghost Borders: `#1E293B`
  - Glass Border Highlights: `rgba(255, 255, 255, 0.08)`
  - Primary Text: `#F8FAFC`
  - Muted Text / Meta: `#94A3B8`
  - Sub-label Text: `#64748B`

## Typography

The typography structure establishes crisp tabular data consumption and modern executive polish.

- **Primary Face (`Inter`)**: Deployed for display titles, structural headings, narrative outputs, and conversational AI responses. Negative tracking is applied to large sizes to impart density and command.
- **Technical Face (`JetBrains Mono`)**: Deployed for countdown numeric figures, fiscal amounts, IRS code section annotations (e.g., `§ 179`, `§ 168(k)`), timestamps, and pill labels. This maintains column alignment and evokes mathematical precision.

## Layout & Spacing

The system prioritizes ergonomic one-handed mobile navigation while maintaining the capacity for dense data ingestion.

- **Mobile Viewport (Primary focus)**: Uses a 4-column fluid system with `margin-mobile` (16px) margins and `gutter-mobile` (12px) gutters. Essential actions and primary input targets are placed within comfortable thumb reach (bottom 40% of the screen).
- **Tablet / Expanded Responsive Reflow**: Expands to an 8-column layout with 24px margins, allowing side-by-side positioning of countdown analytics cards and real-time AI thread outputs.
- **Rhythm**: Component spacing strictly adheres to 4px/8px multiples, establishing consistent vertical tracking between conversational exchanges, input fields, and metric readouts.

## Elevation & Depth

Visual hierarchy is managed through controlled luminous borders and atmospheric dark-mode layering rather than heavy drop shadows:

- **Base Layer (Elevation 0)**: Obsidian surface (`#080C14`), flat with no shadow.
- **Container Layer (Elevation 1)**: Primary cards (`#0F172A`) sitting with a 1px border (`#1E293B`) and a subtle top-edge highlight (`linear-gradient(180deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0) 100%)`).
- **Floating Controls & AI Bubbles (Elevation 2)**: Backdrop-blur modal drawers, bottom sheets, and sticky inputs (`rgba(15, 23, 42, 0.85)` with `backdrop-filter: blur(16px)`), outlined with `rgba(255, 255, 255, 0.12)`.
- **Glow Accents**: Active interactive components (urgent deadline cards, dynamic prompt inputs) produce a localized diffuse glow: `box-shadow: 0 0 20px -5px rgba(16, 185, 129, 0.25)` for primary status and `box-shadow: 0 0 20px -5px rgba(245, 158, 11, 0.2)` for urgent deadlines.

## Shapes

The design uses a balanced rounded architecture:

- **Core Elements**: Standard cards, dialogue boxes, and input fields utilize `0.5rem` (8px) roundedness for an organized, structured feel.
- **Containers & Bottom Sheets**: Employ `rounded-xl` (24px) for expansive cards and sliding drawers to enhance mobile ergonomics.
- **Status Indicators & Filter Chips**: Enforce full pill geometries (`rounded-full` / 9999px) to visually distinguish metadata labels from functional entry cards.

## Components

### Buttons
- **Primary Action**: Emerald background (`#10B981`) with rich slate text (`#080C14`, weight 600). On tap, scales to `0.98` with emerald ring glow.
- **Secondary / Action Ghost**: Glass surface (`rgba(255, 255, 255, 0.04)`) with 1px border (`#1E293B`) and white text (`#F8FAFC`).
- **Destructive / Urgent**: Subtle amber tint fill (`rgba(245, 158, 11, 0.1)`) with amber outline (`#F59E0B`) and amber typography.

### Pill Badges & Chips
- Fully rounded (`rounded-full`), padding `4px 10px`, font `label-sm`.
- **Status AI Verified**: Emerald border with soft background tint (`rgba(16, 185, 129, 0.12)`), `#34D399` text, and a 6px pulsing emerald indicator dot.
- **Status Deadline Approaching**: Amber border (`#F59E0B`) with amber tint (`rgba(245, 158, 11, 0.12)`), `#FBBF24` text.

### Micro-Stat Countdown Cards
- Stacked card format optimized for executive glanceability.
- Displays statutory deadline titles (e.g., "Oct 15 Extension") in `label-sm` muted text, large remaining day counter (e.g., "5 days") in `JetBrains Mono` headline size, and form tag pills (e.g., "Form 1120-S") at the base.
- Urgent states trigger a left accent border (3px solid `#F59E0B`) and ambient warm edge-light.

### Conversational AI Bubbles
- **User Prompt**: Right-aligned, dark slate container (`#1E293B`), neutral text (`#F8FAFC`), rounded corners with lower-right pinch.
- **AI Agent Response**: Left-aligned, full width, borderless glass background (`rgba(15, 23, 42, 0.6)`), 1px border highlight (`rgba(6, 182, 212, 0.2)`), featuring an electric cyan icon chip (`#06B6D4`) in the header. Supports nested markdown tables, tax code citations, and actionable recommendation pills.

### Input Fields & Controls
- **Executive Search / Chat Prompt Bar**: Pill-shaped or soft-rounded (`rounded-lg`) inset well (`#0B1120`), border `1px solid #1E293B`, transitioning to `1px solid #10B981` with a cyan-mint focus bloom on tap. Contains trailing action icons (mic, paperclip, send button).
- **Toggles & Selectors**: Custom emerald tracks (`#10B981`) with deep obsidian knobs (`#080C14`) for swift binary configuration of tax elections (e.g., Section 179 vs. Bonus Depreciation).