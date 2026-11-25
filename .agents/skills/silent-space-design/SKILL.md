---
name: silent-space-design
description: Design and review the Silent Space Cafe Django site using the thesis proposal and editorial design direction.
---

# Silent Space Cafe

The thesis proposal is the source for the cafe concept. The old mockups in design-references are retired. Design for students, readers, freelancers and remote workers. Use warm ivory, espresso, muted olive, restrained brass, serif display type and readable sans-serif body text. Use natural-light photography and label any illustrative imagery.

Keep the homepage journey in order: photo-led hero, spaces, cafe experience, verified menu and reservation request. Preserve dedicated routes, catalogue data, session bag and Admin. Say requests are pending until confirmed. Describe focus lights as a concept and never imply live availability or invent business details.

Check layouts at 390, 768 and 1440 pixels. Verify keyboard navigation, bag actions and valid and invalid reservation submissions.

Standing user rule: every customer-facing page must use the homepage's identical shared header and footer. The header stays warm ivory with espresso branding/navigation and an olive Reserve a seat button; the shared espresso footer and useful links stay consistent. Use `templates/base.html` and shared styles. Do not add page-specific header/footer colours, typography, sizing or responsive variants, even when a new mockup shows a different header/footer. Preserve active-link semantics and the dynamic bag count. See the repository `AGENTS.md`.
