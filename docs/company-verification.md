# Company verification and route discovery

Verify the employer before spending time on an application, then use the same research to find the best official application route.

## Evidence rule

Treat each signal as evidence, not proof on its own. A company can be marked `verified` only when all of these are present:

1. its official website;
2. its LinkedIn company page; and
3. at least one independent operational signal: a business registry, the company's ATS, an app-store publisher record, or a matching Google Maps business presence.

Check that names, domains, addresses and phone numbers agree. Record review sites as context, not as identity proof. Employee activity can strengthen a LinkedIn signal, but does not replace the source links above.

Use `unknown` when research is incomplete. Use `review` when evidence conflicts or a risk remains, including lookalike domains, unexpected redirects, certificate errors, or mismatched contact details. Never turn missing evidence into a negative claim.

## Verified routes

Prefer, in order: the exact job page, a verified ATS listing, the official careers page, a verified recruiter profile, then an email published by the company. Every route must include the public page where it was found. Never construct an email address, infer an ATS URL, or copy a contact from an unverified repost.

A broken tracking link does not by itself make the employer fraudulent. Inspect the final destination separately, record the redirect/certificate risk, and use a direct official route only when its provenance is clear.

## Recording research

Workers may store a `CompanyVerification` record from `findmejob.verification`. The validator enforces source URLs, the three-signal rule, official-domain consistency for email, unresolved-risk review, and preservation of unknown status. The tracker exposes the best source-backed route without overwriting the original listing URL.

Example data shape (fictional):

```json
{
  "company": "Example Co",
  "status": "verified",
  "official_domain": "example.com",
  "evidence": [
    {"kind": "official_website", "url": "https://example.com"},
    {"kind": "linkedin", "url": "https://www.linkedin.com/company/example"},
    {"kind": "ats", "url": "https://jobs.example.com"}
  ],
  "routes": [
    {
      "kind": "ats",
      "value": "https://jobs.example.com/opening/123",
      "source_url": "https://example.com/careers",
      "verified": true
    }
  ],
  "risks": []
}
```

Keep research records in the local tracker. Do not commit real candidates, credentials, private recruiter conversations, or application history to this public repository.
