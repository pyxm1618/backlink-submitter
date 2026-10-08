# WYRPlay — Final Submission Field Policy

This package is exclusively for **WYRPlay**.

## Hard project isolation
Allowed:
- `project_id = wyrplay`
- brand = `WYRPlay`
- domain = `wyrplay.com` / `www.wyrplay.com`

The Quick I Ching-related strings in the machine-readable deny list exist only as contamination guards.
They are never valid submission content.

If an outgoing payload contains content from another project, abort before Submit.

## Public email
Use **support@wyrplay.com** for public-facing product/contact fields.

## Product classification
WYRPlay is a non-AI Would You Rather social/question game.
Do not use AI / LLM / GPT categories and do not submit it to AI-only directories.

## Logo rule
Use only:
- `assets/logo/wyrplay-logo.png`
- `assets/logo/wyrplay-logo.svg`

These are the owner-confirmed authoritative logo files.

## No fabrication
Unknown fields must remain blank if optional, or require manual review if mandatory.

Verified legal operator: `Wang Yufei`.
Do not automatically convert the legal operator into a `Founder` field.
