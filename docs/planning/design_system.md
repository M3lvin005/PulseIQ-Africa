# PulseIQ Africa Interface System

Version: 0.2.0 prototype contract  
Last verified: 2026-08-27  
Scope: Streamlit validation shell and the contract for the later production web client

## 1. Product expression

PulseIQ is a governed decision workspace, not a generic KPI dashboard. Every screen should answer, in order:

1. What evidence is active?
2. Is its meaning and quality sufficient for this task?
3. What requires attention?
4. What action is available and who remains accountable?

The workspace trust ribbon—source → meaning → quality → next action—is the signature pattern. Cobalt means action or selection. Green means healthy or approved. Amber and red are reserved for state and never used decoratively.

## 2. Semantic colour contract

Components consume semantic tokens only; they must not switch on a theme name or embed palette values locally.

| Role | Light | Dark | Rule |
|---|---:|---:|---|
| Canvas | `#F3F6FA` | `#09111F` | Page background |
| Surface | `#FFFFFF` | `#111B2D` | Cards, rail, charts, tables |
| Raised surface | `#FFFFFF` | `#162238` | Alerts and elevated controls |
| Field | `#FFFFFF` | `#0E1829` | Inputs and upload areas |
| Heading | `#0B1739` | `#EDF2FF` | Titles and strong labels |
| Body text | `#1D2433` | `#DDE5F3` | Primary reading text |
| Muted text | `#5F6B7C` | `#AAB6C8` | Secondary text; still AA |
| Border | `#DCE3EE` | `#2C3A52` | Default separation |
| Action | `#3154F5` | `#8398FF` | Primary actions and selection |
| Action tint | `#E9EDFF` | `#22315C` | Selected backgrounds |
| Analytic support | `#35BFEA` | `#66CAE9` | Secondary chart series only |
| Healthy | `#087A5B` | `#58D2AD` | Healthy/approved status |
| Warning | `#976000` | `#F0C66D` | Human review required |
| Danger | `#B9382F` | `#FF938A` | Error/destructive/blocking |

Implemented normal-text pairs meet or exceed 4.5:1. Dark text/surface is 13.60:1, dark muted/surface 8.40:1, dark action/canvas 7.11:1, light text/canvas 14.33:1, light muted/surface 5.41:1, and white/light-action 5.65:1.

## 3. Appearance modes

- `System` is the first-run default and follows `prefers-color-scheme` without client script.
- `Light` and `Dark` are explicit overrides and must win over system preference.
- The current Streamlit choice is session-scoped and survives reruns/navigation. The production client must persist the explicit choice in local storage or the user profile, apply it before hydration, and avoid a theme flash.
- Native controls declare the matching `color-scheme`. Charts, tables, fields, alerts, focus rings, and overlays consume the same tokens.
- Theme is preference, not meaning: labels, icons, chart shapes, and status language remain identical.
- A framework, Plotly, or token change triggers contrast plus rendered chart/table regression tests in both themes.

## 4. Spacing and alignment

The base unit is 4 px. Allowed spacing steps are `4, 8, 12, 16, 24, 32, 48, 64` px.

| Context | Default | Rule |
|---|---:|---|
| Phone page gutter | 12 px | Never below 12 px at 320 px |
| Tablet/desktop page gutter | 20–36 px | Grows with available width |
| Card padding | 16 px | 12 px only for dense secondary content |
| Hero padding | 17–32 px | Fluid with `clamp`; never crowds text |
| Grid/column gap | 16 px | 12 px on narrow phone compositions |
| Section gap | 24–32 px | Separate tasks, not individual fields |
| Label/control gap | 8 px | Helper text follows at 4–8 px |
| Fixed mobile-nav inset | 10 px | Plus safe-area bottom inset |

Rules:

- Align headings, trust ribbon, cards, charts, and tables to the same content edge.
- Do not use arbitrary one-off margins where a spacing token works.
- Prefer internal padding over empty spacer elements.
- Keep reading lines around 60–75 characters and never widen prose just because a table can grow.
- Cards in one row use equal visual padding; their height may follow content unless comparison requires equal height.
- Fixed controls must reserve document padding and must not cover content, focus, error messages, or browser safe areas.

## 5. Shape, elevation, type, and motion

- Radius: 6 px compact, 10 px controls, 14 px cards, 18 px major/floating surfaces. Pills are reserved for short statuses and segmented controls.
- Shadows indicate layering, not decoration. Base cards use a subtle shadow; only fixed overlays use the floating shadow.
- Use a system sans stack or self-hosted Inter. Body starts at 16 px with 1.5–1.65 line height. Phone hero copy may use 14 px with 1.5 line height.
- Use tabular numerals for amounts, percentages, counts, IDs, and tables. Use sentence case.
- Transitions are 160 ms for colour/border changes. Motion must not gate state and is reduced to effectively zero under `prefers-reduced-motion`.

## 6. Responsive composition

| Width | Navigation and chrome | Content behavior |
|---|---|---|
| 320–479 px | Fixed five-item bottom navigation; no desktop rail/header | One action-first column; full-width cards; 12 px gutter |
| 480–767.98 px | Same mobile composition | One or two columns only when each remains at least 220 px |
| 768–1023 px | Framework-collapsible rail with visible expand control | Wrapped analytic columns; filters collapse before content |
| 1024–1439 px | Persistent 300 px labeled rail | Dense two-column evidence/attention layout |
| 1440 px and above | Persistent rail | Wider charts/tables; prose width remains bounded |

The boundary is intentional: the mobile media query ends at 767.98 px so fractional CSS pixels do not create a one-pixel navigation gap. Desktop and mobile primary navigation must never be visible together. All breakpoints must have zero document-level horizontal overflow.

## 7. Component rules

### Navigation

- Desktop uses one labeled workflow rail. Phone uses exactly five primary destinations: Overview, Data, Portfolio, Risk, More.
- Both controls update the same route/page state. Current destination is conveyed programmatically and visually.
- Minimum primary touch target is 44 px; implemented phone destinations are at least 50 px high.

### Theme switcher

- Use a compact System/Light/Dark segmented control in the upper-right safe region.
- The accessible group name is `Appearance`; its visible label may be visually hidden when the three options are self-explanatory.
- It stays separate from decision status and does not displace the H1 at phone widths.

### Trust ribbon

- Always preserve the order source, meaning, quality, next action.
- Show unavailable, warning, blocked, and ready in words; colour is supplementary.
- Long evidence values truncate visually but retain a full accessible/title value.

### Ordered workflows

- Use numbered stages only when order changes what the user can safely do, such as source → meaning → quality → use.
- Every stage exposes its status in words such as loaded, confirmed, warning, blocked, or ready; colour and numbered markers are supplementary.
- Desktop may show four stages in one row. Tablet uses two columns and phone uses one column without changing reading order.
- A stage cannot imply completion when the backing capability does not exist. The prototype therefore says “confirm meaning first” rather than presenting a false activation action.

### Evidence scope and delivery

- Scope filters name the dimension they change, announce the matching record count, and preserve the source version/fingerprint in the trust ribbon. Filtering changes the analytical view only; it never rewrites source evidence.
- Portfolio surfaces lead with decision measures and one or two high-signal comparisons. Secondary distributions belong behind an explicit disclosure region with a table alternative.
- Report delivery is ordered snapshot → definitions → disclosures → downloads. The preview must show source, row count, quality, rule coverage, model status, and observations before export.
- Accessible HTML is the primary report artifact. PDF, CSV, and XLSX are companion formats and must retain the same unavailable states and source metadata.

### Model and assistant evidence

- Model exploration uses the sequence snapshot → eligibility → validation → human review. A score control is unavailable until eligibility passes and a model run exists.
- Model status is always written as approved/unapproved, calibrated/uncalibrated, and explanation available/unavailable; never communicate readiness through colour alone.
- Assistant answers show an Answer heading, deterministic source path, and a disclosure containing source, rows, period, filters, rule version, and model status. Answers link users back to row-level or report evidence for consequential interpretation.

### Contrast-safe glass surfaces

- Every semantic foreground token must be applied to the current framework's real DOM selectors, including React-Aria comboboxes, metric labels, popovers, option rows, segmented controls, and icon buttons. Test rendered computed styles in both explicit themes.
- Glass is a hierarchy accent, not a content background: use it on workflow/filter/navigation containers with a tinted opaque fallback. Keep metrics, tables, forms, and chart canvases opaque enough that text contrast does not depend on backdrop imagery.
- Interactive glass controls require a visible border, hover state, keyboard focus ring, and selected state whose text/background pair is independently readable in Light and Dark modes.

### Metrics and cards

- A metric includes label, value or explicit unavailable state, unit/period, and definition help where needed.
- Never turn missing input into zero. Avoid “healthy” styling until the relevant capability is actually ready.
- Cards group one task or one comparison; avoid nested card stacks.

### Forms and actions

- One clear primary action per task region; secondary actions remain visually quieter.
- Labels remain programmatic and helper/error text stays adjacent. Validation preserves entered data and explains recovery.
- Destructive actions require consequence text and the appropriate confirmation/undo policy.

### Tables and charts

- Trend → line, category comparison → sorted bar, distribution → histogram/box. Avoid pie/donut for operational risk.
- Plot and paper backgrounds are transparent to the semantic surface. Axes, grid, legends, and titles inherit theme tokens.
- Every chart has a textual insight and a named table/export alternative. Status is represented with text plus shape/icon, not hue alone.
- Tables use captions and scoped headers; large framework grids require CSV/semantic alternatives.
- Review queues keep filters outside the immutable evidence result. Filtering changes only the visible/downloaded subset and always states the matching record count.

### Feedback and overlays

- Success, warning, error, and information messages use the same semantic role in both themes.
- Toasts are transient confirmation, not the only record of a consequential outcome.
- Dialogs trap focus, restore it on close, and keep the initiating context visible where practical.

### Evidence inspectors and progress

- An inspector receives a filtered evidence set and stable identifier, then exposes the selected source record, status, rule/quality evidence, provenance, and safe actions. Desktop uses an adjacent panel; mobile uses a full-width expansion.
- Selectors preserve the active filters, dataset/version, and return path. Large sets are capped or paginated in the prototype and must use virtualized/search-backed results in production.
- Long-running work uses one job contract: stable ID, phase, percent/state, heartbeat, cancellation, retry/error, and artifact reference. Local progress and the Activity Center must never show success before the backing callback or worker result succeeds.

## 8. Accessibility and quality gate

- Target WCAG 2.2 AA: normal text ≥4.5:1; large text and meaningful non-text UI ≥3:1.
- One H1, sequential headings, visible skip link, visible 3 px focus ring, keyboard parity, and no focus obscured by fixed chrome.
- Respect reduced motion. Do not rely on hover, drag, gesture, colour, or animation alone.
- Verify 320, 375, 767, 768, 1024, and 1440 CSS px; both themes; keyboard; representative empty/error/partial/loaded data; chart tables; actual 200% zoom; NVDA and VoiceOver before production approval.
- Automated checks are necessary but do not constitute WCAG certification. Residual Streamlit landmark and Plotly graph-name limitations remain documented in `accessibility_verification.md`.

## 9. Implementation boundary

`src/pulseiq/ui.py` is the prototype token and component-style source. This document is the portable contract; the later production client should expose the same semantics through typed design tokens and independently tested components rather than copying Streamlit selectors.
