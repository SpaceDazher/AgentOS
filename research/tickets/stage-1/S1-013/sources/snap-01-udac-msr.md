# Retrieval record (not a source claim)

- snapshot: snap-01-udac-msr.md
- canonical_uri: https://www.microsoft.com/en-us/research/publication/user-driven-access-control-rethinking-permission-granting-in-modern-operating-systems-2/
- version: Proceedings of the IEEE Symposium on Security and Privacy,
  May 2012, Best Practical Paper (DOI 10.1109/sp.2012.24)
- authors: Franziska Roesner, Tadayoshi Kohno, Alex Moshchuk,
  Bryan Parno, Helen Wang, Crispin Cowan
- retrieved_at: 2026-09-04T00:00:00Z (UTC)
- method: webfetch-text of the publication landing page; substantive
  fragment archived below (title, authorship, venue, abstract).
  Navigation chrome omitted; see the reproducibility limit.
- reproducibility_limit: fragment (title/authors/venue/abstract), not
  full-page bytes and not the paper PDF. No sentence beyond the
  abstract is attributed to this page.
- use: primary HCI evidence for in-context, non-disruptive,
  least-privilege approval design (approval-load conditions,
  anti-fatigue grouping that must not hide actor/action/scope/expiry).

# Archived fragment (verbatim)

Title: User-Driven Access Control: Rethinking Permission Granting in
Modern Operating Systems

"Modern client platforms, such as iOS, Android, Windows Phone,
Windows 8, and web browsers, run each application in an isolated
environment with limited privileges. A pressing open problem in such
systems is how to allow users to grant applications access to
user-owned resources, e.g., to privacy- and cost-sensitive devices
like the camera or to user data residing in other applications. A key
challenge is to enable such access in a way that is non-disruptive to
users while still maintaining least-privilege restrictions on
applications."

"In this paper, we take the approach of user-driven access control,
whereby permission granting is built into existing user actions in
the context of an application, rather than added as an afterthought
via manifests or system prompts. To allow the system to precisely
capture permission-granting intent in an application's context, we
introduce access control gadgets (ACGs). Each user-owned resource
exposes ACGs for applications to embed. The user's authentic UI
interactions with an ACG grant the application permission to access
the corresponding resource. Our prototyping and evaluation experience
indicates that user-driven access control enables in-context,
non-disruptive, and least-privilege permission granting on modern
client platforms."
