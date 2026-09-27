# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

(An Electron desktop app for Windows and macOS. The UI is a SolidJS renderer, so it follows web conventions inside a native window with a custom titlebar.)

## Users

Anyone applying for jobs, not one particular profile. They are applying to many roles across employer portals (Workday, Greenhouse, Lever, Ashby, iCIMS and unknown ones), usually in bursts, on their own computer. They hand over their materials once, queue job links, and come back to read what was filled and approve it. Most are not technical and should never need to understand the automation to trust it.

## Product Purpose

Applyocalypse fills job applications for the user. It tailors the resume and cover letter to each posting, drives the employer's portal in a real browser, answers the questions from the user's own profile, and stops at the end so the user can read everything and press submit. Success is an application that is complete, correct and in the user's own words and layout, taking minutes of reading instead of an hour of typing.

## Positioning

Local-first and human-controlled. Documents, profile and credentials stay on the user's machine. The AI does all the filling on any portal, including ones it has never seen, and pauses to ask instead of guessing. Nothing is sent to an employer until the user has read it and approved it. Tailored resumes are written into the user's own document layout, not a generic template.

## Operating Context

- Onboarding, done once: resume (required), cover letter (optional), additional documents (optional), then the user's details. Details cover identity and contact, work history with a reason for leaving each position, education, work authorization, demographic (EEO) answers, legal and background answers, and up to three references (name, relationship, company, email, phone).
- Daily loop: paste job links, watch runs progress, answer the occasional pause (CAPTCHA, one-time code, an unclear question, an account wall), then review the filled application and submit.
- Runs happen in a visible browser window the app supervises. Several can run at once, up to the user's limit.
- LLM provider keys, the Jev gateway key, portal login and the Gmail connection are entered in Settings.

## Capabilities and Constraints

- The app never submits without the user's explicit approval at the review step.
- Demographic, criminal-history and previous-employer answers (including reason for leaving) are always held for review, even when pre-filled from the profile.
- Secrets are encrypted at rest and never logged. Documents live on disk, never inside the database.
- Generated text never contains em dashes or the banned-word list.
- Fonts and assets are bundled; the renderer makes no network requests for them.
- Open decision: the user wants an optional "submit automatically" mode. This conflicts with the current approval invariant and is not built until it is explicitly signed off, including how held-for-review answers behave under it.

## Brand Commitments

- The name stays "Applyocalypse".
- Light mode is the primary experience; dark mode is supported and must feel intentional, but light is designed first.
- The user explicitly rejected the previous look (steel/cobalt/citron, Hanken Grotesk + JetBrains Mono) as feeling AI-generated. Nothing from it carries forward.

## Evidence on Hand

No testimonials, metrics, customers or press exist. Do not invent any. Real content available: the user's own profile, documents, job queue and run history inside the app.

## Product Principles

1. The user reads, the AI types. Every screen should make reviewing fast and filling invisible.
2. Pause, don't guess. Uncertainty is shown plainly and handed to the user.
3. Nothing leaves without a yes. The submit moment is the most important moment in the product.
4. It is the user's material. Their resume, words and answers are shown as theirs, not as AI output.
5. Calm under load. Many runs at once should read as order, not noise.

## Accessibility & Inclusion

Keyboard-operable throughout with visible focus. Screen-reader labels on all controls. Text contrast at WCAG AA or better in both themes. Respects reduced motion. Demographic questions always offer "prefer not to say" and are never pre-filled.
