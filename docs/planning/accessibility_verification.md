# Rendered Accessibility and Responsive Verification

Date: 2026-08-27  
Scope: stabilized Streamlit prototype, synthetic data only  
Standard target: WCAG 2.2 AA; this evidence is not a conformance certification

## Automated and rendered evidence completed

- Native Streamlit AppTest covers empty, blocked, upload navigation, governed dashboard, rule, model eligibility, report, and demo states.
- The app was rendered in the Codex in-app Chromium browser and inspected at 320, 375, 767, 768, 1024, and 1440 CSS-pixel breakpoints. The trust-first shell, fixed controls, theme switcher, and populated chart were rechecked after the semantic theme implementation.
- No document-level horizontal overflow or clipped main-content element was found at those breakpoints.
- At 320 and 375 px, Overview and Data content stack into one readable column and a native five-destination radio navigation remains fixed above the safe-area edge. Its Data control was browser-exercised and opened the real Upload Data screen.
- The desktop rail and mobile bottom control are never visible together. The mobile query ends at 767.98 px; browser checks on both 767 and 768 px prove there is no one-pixel navigation gap. At 768 px, the mobile control is hidden and Streamlit's visible keyboard-operable expand control restores the rail; desktop cards wrap without truncation.
- System, Light, and Dark are exposed as one native segmented radiogroup named `Appearance`. An explicit Dark choice survived the rerun caused by mobile navigation to the Data screen.
- The fixed appearance control does not intersect the hero or mobile navigation at 320 or 375 px. The bottom navigation does not intersect the hero, reserves 108.8 px document padding, and keeps five 50 px-or-taller destinations above the safe-area edge.
- Heading order is H1 then H2 on every inspected page; the sidebar brand is no longer a competing H1.
- The Home call to action now changes the keyed workspace state and lands directly on Upload Data.
- A keyboard-visible skip link targets `#main-content`; the focused link has a 3 px blue outline and the target accepts focus.
- App-authored focus styling, reduced-motion overrides, escaped custom HTML, and semantic action/status separation remain in place.
- The browser-visible file-uploader limit now matches the 10 MB parser policy.
- Every Plotly chart is followed by a named expandable table alternative. Compact governance tables use escaped semantic HTML with a caption, `scope="col"`, and `scope="row"`.
- The full demonstration model interaction rendered without exceptions and exposed only an uncalibrated score, manual-review routing, and explanation unavailable.
- The implemented static token pairs remain above 4.5:1 for normal text. Light examples include text/canvas 14.33:1, muted/surface 5.41:1, and white/action 5.65:1. Dark examples include text/surface 13.60:1, muted/surface 8.40:1, action/canvas 7.11:1, healthy/surface 9.22:1, warning/surface 10.67:1, and danger/surface 8.04:1.
- In both explicit themes, rendered Plotly paper/plot backgrounds are transparent to the card surface; ticks inherit body text and grid lines inherit borders. Theme and document geometry had zero horizontal overflow at the checked widths.
- The Data intake and Risk review slice was additionally rendered at 320, 375, and 1440 px in both semantic palettes. The ordered intake reflows from four columns to one without changing source order, and the three Risk filters stack to full width on phone.
- The intake heading hierarchy was corrected to H1 → H2 after rendered inspection. Loading sample data now runs as a pre-render callback, so the sidebar source, workflow stage, currency, and quality state update in the same render.
- The Risk queue's Priority control was browser-exercised from all 735 flags to the two High-priority flags; the visible count and filtered download remained available. The page explicitly states that a flag is not a fraud finding, case disposition, or final decision.

## Residual manual or platform work

- Run NVDA + Firefox/Chrome and VoiceOver + Safari task scripts with representative analysts. The current environment does not provide those assistive technologies.
- Run a supported axe-core integration in CI when a maintained Streamlit browser harness is selected. Native AppTest does not execute axe.
- Verify actual browser 200% zoom manually. The 320 px reflow check exercises the equivalent narrow layout but does not prove browser zoom behavior.
- Streamlit's root currently renders as a `section` without a native `main` landmark and its sidebar lacks a native `nav` landmark. The skip link mitigates navigation cost, but landmark remediation depends on the selected production web shell or an upstream Streamlit change.
- Large Streamlit data grids remain framework widgets. They are keyboard-operable and have named controls, while exported CSV and compact semantic tables provide alternatives; complete screen-reader grid behavior still needs manual verification.
- Plotly's rendered graph containers do not expose useful ARIA names in this stack. The adjacent captions and semantic tables are the supported accessible representation.
- Color, focus, keyboard, screen-reader, reduced-motion, and chart-table behavior must be independently retested after any theme token, Streamlit, Plotly, or production-shell upgrade.
- Prototype appearance persistence is session-scoped. The production shell still needs pre-hydration user/system preference resolution, durable preference storage, and a no-flash browser test.

## Exit interpretation

No critical app-authored blocker was left in the inspected flows. Phase 1 accessibility approval still requires the manual assistive-technology and actual-zoom checks above plus acceptance of, or migration away from, the Streamlit landmark limitations.
