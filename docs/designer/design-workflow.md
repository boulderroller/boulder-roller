# Boulder Rollers - Design Workflow Guide

## Overview

This document outlines the design-to-development workflow for the Boulder Rollers project. Since development has already begun using Claude Code, this workflow integrates design into the existing development process.

---

## Workflow Philosophy

**Component-Level, Feature-Driven Design**
- Design work is scoped to specific features/pages as they're prioritized for MVP
- Components are designed when needed, not all upfront
- Each feature gets the full design → implement → learn cycle

**Iterative Development**
- Work in short cycles: design → implement → review → iterate
- Learn from each feature to inform the next
- Allow for course corrections based on real implementation learnings

**Living Design System**
- Design system grows organically with the product
- Document patterns and components as they're created
- Build reusability over time, not all at once

---

## The Team

**Product Designer**
- Creates high-fidelity designs in Figma
- Defines visual design system (colors, typography, spacing)
- Makes component design decisions
- Reviews implemented features for design quality

**Developer**
- Builds features using Claude Code
- Maintains the codebase and GitHub workflow
- Reviews and merges pull requests
- Provides technical constraints/guidance

**Design-to-Code Bridge** (Claude in chat)
- Translates Figma designs into production code
- Generates components that match existing code patterns
- Helps maintain design system documentation
- Provides implementation recommendations

---

## The Workflow Cycle

### Phase 1: Feature Planning
**Who:** Designer + Developer (together)

**Activities:**
1. Review MVP scope and prioritize next feature
2. Discuss technical constraints or dependencies
3. Agree on success criteria for the feature
4. Designer takes ownership of design phase

**Output:** Clear understanding of what's being designed and why

---

### Phase 2: Design in Figma
**Who:** Designer

**Activities:**
1. Create/refine components needed for the feature
2. Design all states (default, hover, active, disabled, error, loading, empty)
3. Design responsive breakpoints if needed
4. Document any new design tokens (colors, spacing, etc.)
5. Ensure accessibility considerations (contrast, focus states)

**Output:** 
- High-fidelity Figma designs
- Specifications for new design tokens
- Any design decisions that need documentation

**Tips:**
- Design mobile and desktop if the feature requires it
- Include edge cases and empty states
- Note any animations or transitions
- Call out any interactive behaviors

---

### Phase 3: Design Handoff
**Who:** Designer → Claude (via chat)

**Activities:**
1. Share Figma designs with Claude (screenshots, links, or exports)
2. Provide context about:
   - What feature/component this is
   - Any technical requirements or constraints
   - Which existing components this should match/reuse
   - Any special interactions or behaviors
3. Clarify any questions Claude has about the design

**Output:** Claude has everything needed to generate code

**What to Share:**
- Screenshots of the final designs
- Figma link (if accessible)
- Exported assets (images, icons, etc.)
- Design specifications (spacing, colors, typography)
- Notes about interactions/animations

---

### Phase 4: Code Generation
**Who:** Claude

**Activities:**
1. Analyze the designs and requirements
2. Generate production-ready code that matches:
   - Your design specifications
   - Existing code patterns in the project
   - Project's tech stack and conventions
3. Provide complete component files
4. Update design system documentation

**Output:**
- Complete, copy-paste-ready code files
- Updated design system documentation
- Implementation notes if needed

---

### Phase 5: Local Implementation
**Who:** Designer

**Activities:**
1. Copy the generated code into your local project
2. Create new files or update existing ones as directed
3. Test the feature locally:
   - Visual accuracy compared to designs
   - Interactive states work correctly
   - Responsive behavior (if applicable)
   - No console errors
4. Make any minor adjustments needed
5. Commit changes to a feature branch

**Output:** Working feature in your local environment

**Testing Checklist:**
- [ ] Matches Figma design visually
- [ ] All interactive states work (hover, active, disabled)
- [ ] Responsive breakpoints function correctly
- [ ] No console errors or warnings
- [ ] Accessible (keyboard navigation, screen reader friendly)
- [ ] Works in target browsers

---

### Phase 6: Pull Request
**Who:** Designer

**Activities:**
1. Push feature branch to GitHub
2. Create pull request with:
   - Clear description of what was added/changed
   - Screenshots of before/after (if applicable)
   - Link to Figma designs
   - Any notes for the developer
3. Request review from your partner

**Output:** PR ready for developer review

**Good PR Description Template:**
```
## Feature: [Feature Name]

### What's Changed
- Added [component name] component
- Updated [page name] page with new design
- Implemented [specific feature]

### Design Reference
[Link to Figma design]

### Screenshots
[Before/After screenshots]

### Testing Done
- [ ] Visual review against designs
- [ ] Tested interactive states
- [ ] Responsive behavior checked
- [ ] No console errors

### Notes
[Any additional context for reviewer]
```

---

### Phase 7: Review & Merge
**Who:** Developer

**Activities:**
1. Review PR for:
   - Code quality and patterns
   - Technical implementation
   - Performance considerations
   - Browser compatibility
2. Test feature locally
3. Request changes if needed, or approve
4. Merge to main branch
5. Deploy (if applicable)

**Output:** Feature shipped to production

---

### Phase 8: Update Design System
**Who:** Designer + Claude

**Activities:**
1. Document new components in design system
2. Add any new design tokens (colors, spacing values, etc.)
3. Update component library in Figma (if maintaining one)
4. Note any learnings or patterns for future features

**Output:** Updated design system documentation

---

## Design System Documentation

As features are built, we maintain a living design system document that includes:

### Foundation
- **Colors:** All color tokens with hex values and usage
- **Typography:** Font families, sizes, weights, line heights
- **Spacing:** Spacing scale (4px, 8px, 16px, etc.)
- **Shadows:** Shadow definitions for elevation
- **Border Radius:** Corner radius values
- **Breakpoints:** Responsive design breakpoints

### Components
For each component:
- **Purpose:** What it's used for
- **Variants:** All variations (primary/secondary, sizes, etc.)
- **States:** Default, hover, active, disabled, error, loading
- **Props/Attributes:** What can be customized
- **Usage Guidelines:** When to use, when not to use
- **Code Example:** How to implement
- **Accessibility Notes:** Any a11y considerations

### Patterns
- **Empty States:** How to handle no content
- **Loading States:** Skeleton screens, spinners
- **Error States:** How to display errors
- **Form Patterns:** Input fields, validation, submission
- **Navigation Patterns:** How users move through the app
- **Modal Patterns:** Dialogs, overlays, confirmations

---

## Communication Guidelines

### When to Sync with Developer
- Before starting a new feature (to confirm scope)
- When design decisions impact backend/data requirements
- If you discover technical constraints during design
- After implementing, if something doesn't work as expected

### When to Work with Claude
- When you have Figma designs ready to implement
- When you need code for a new component
- When updating the design system documentation
- When you have questions about implementation approach

### What to Document
- All design decisions and rationale
- New design tokens or patterns
- Component usage guidelines
- Any deviations from established patterns (and why)

---

## Tools & Resources

### Design Tools
- **Figma:** Primary design tool for mockups and components
- **Figma Plugins (suggested):**
  - Stark (accessibility checking)
  - Contrast (color contrast verification)
  - Lorem Ipsum (placeholder content)

### Development Tools
- **Claude Code:** Developer's primary coding assistant
- **Claude Chat:** Designer's code generation assistant
- **GitHub:** Version control and collaboration
- **Local Development:** Testing implementations before PR

### Documentation
- **Design System Doc:** Living document in the repository
- **This Workflow Guide:** Reference for the process
- **Audit Document:** Analysis of current state and opportunities

---

## Best Practices

### For Designer
1. **Always design all states:** Default, hover, active, disabled, error, loading, empty
2. **Consider edge cases:** What happens with very long text? No data? Errors?
3. **Design mobile-first:** Start with mobile constraints, expand to desktop
4. **Be consistent:** Reuse existing patterns before creating new ones
5. **Document decisions:** Why you made certain design choices
6. **Test your implementations:** Don't just copy code, verify it works
7. **Communicate early:** Flag potential technical issues during design, not after

### For Developer
1. **Provide technical context early:** Share constraints before design begins
2. **Review PRs promptly:** Keep the design iteration cycle moving
3. **Give constructive feedback:** Explain technical concerns clearly
4. **Maintain code quality:** Don't sacrifice code quality for design accuracy
5. **Update Claude on patterns:** Let the designer know if coding patterns change

### For Both
1. **Iterate quickly:** Small, frequent cycles beat large, infrequent ones
2. **Build the MVP mindset:** Perfect is the enemy of shipped
3. **Document as you go:** Don't save documentation for later
4. **Celebrate wins:** Acknowledge when features ship successfully
5. **Learn from mistakes:** Retrospect on what could improve

---

## Troubleshooting

### "The generated code doesn't match our existing patterns"
**Solution:** Share example files from your codebase with Claude so it can match your conventions.

### "The design looks different when implemented"
**Solution:** 
1. Check if design tokens (colors, spacing) match specifications
2. Verify browser/device being tested
3. Check if responsive breakpoints are correct
4. Share screenshots with Claude to debug

### "We need to change something after it's merged"
**Solution:** Treat it like a new feature iteration - design the change, generate code, PR, merge. Small iterations are fine!

### "The component is too complex to build in one go"
**Solution:** Break it into phases. Ship a simpler version first, enhance later. MVP thinking applies to features too.

### "We're not sure if this should be a new component or variant"
**Solution:** 
- If it's >70% similar to existing component → Make it a variant
- If it's <70% similar → Make it a new component
- When in doubt, start as variant, split later if needed

---

## Success Metrics

How do we know this workflow is working?

1. **Velocity:** Are we shipping features at a good pace?
2. **Quality:** Do implemented features match designs accurately?
3. **Consistency:** Are we building reusable patterns?
4. **Developer Experience:** Is the process smooth for your partner?
5. **Designer Experience:** Are you able to see your designs come to life efficiently?
6. **User Experience:** Are we building something users will love?

Regular check-ins (weekly or bi-weekly) to discuss what's working and what needs adjustment.

---

## Version History

- **v1.0** - January 28, 2026 - Initial workflow document created

---

## Questions?

If anything in this workflow is unclear or needs adjustment:
- Discuss with your development partner
- Bring questions to Claude during design handoff
- Update this document as the workflow evolves

Remember: **This is a living document.** Update it as you learn what works best for your team.

---

*This workflow is designed to be flexible and adaptive. Start here, then customize based on what works for your team.*
