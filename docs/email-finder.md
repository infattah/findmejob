# Email finder

A relevant job is worth little if your CV never reaches a person. findmejob treats delivery as two routes for every qualified role:

1. the portal application (`findmejob apply`), and
2. a short follow-up email to a verified company address, asking them to pass it to the hiring team.

`findmejob emails` finds that address. It is strict about what "found" means.

## The rules

- **Never guess.** No `careers@company.com` because it is a common pattern. Every address in a report was read from a public page, and the report keeps that page's URL.
- **Verified means three things together:** the address was published on the job listing or on a page of the company's own confirmed domain; its domain matches that official domain (or the listing printed it directly); and the domain has a live MX record.
- **"No verified address" is a conclusion.** It is only reported when every method actually ran and none produced a verified address. If a method could not run - no search provider, blocked search, unknown domain, DNS lookup failed - the hunt is `incomplete` and says which methods are still missing.

## The methods

| Method | What it reads |
| --- | --- |
| `listing` | Addresses printed in the job description. `findmejob search` already captures these as `contact_emails`. |
| `official_site` | The official domain's homepage plus contact, careers, jobs, join-us and about pages, and same-domain links that look like them. Handles `mailto:` and `name [at] company [dot] com`. |
| `web_search` | Search results for the company with careers/HR/contact terms, and for `"@officialdomain"`. |
| `linkedin` | LinkedIn company and recruiter results, plus any LinkedIn pages you supply. |
| `registry` | Business registry and directory results (configurable sites), plus any registry pages you supply. |
| `mx` | DNS MX lookup (over HTTPS) for every candidate address's domain. |
| `pattern` | Checks found addresses: domain matches the official domain, not a lookalike domain, not free-mail, not `noreply@`. It verifies; it never generates. |

Addresses found on third-party pages (directories, LinkedIn, search snippets) are kept as leads with notes, but they are not marked verified unless the company publishes them itself.

When several verified addresses exist, hiring inboxes (`careers@`, `jobs@`, `recruitment@`, `hr@`) are preferred over named people, and named people over general inboxes like `info@`.

## Using it

```bash
findmejob emails --job <id> --domain example.com --confirmed
findmejob emails --all                      # every applied/ready/shortlisted role whose hunt is missing, incomplete or failed
findmejob emails --job <id> --pages pages.json   # add pages you or your agent opened
findmejob emails --job <id> --outcome sent --proof <sent-message id or link>
findmejob emails --job <id> --outcome failed --proof "bounced"
```

If `--domain` is omitted, the official domain from the role's company verification record is used, and it counts as confirmed only when that record is `verified` (see [company-verification.md](company-verification.md)).

LinkedIn and many registries block automated reading. When your coding agent (Claude Code, Codex, ...) or you open those pages in a browser, pass them in:

```json
[
  {"method": "linkedin", "url": "https://www.linkedin.com/company/example", "text": "...page text..."},
  {"method": "registry", "url": "https://registry.example/company/123", "text": "...page text..."}
]
```

## Tracker states

For applied roles, `findmejob status` splits the email route into:

- **email sent** - with proof recorded (sent-message id or link); a sent email requires a verified address on record;
- **email pending** - a verified address exists, follow-up not sent yet;
- **email failed** - the send failed or bounced; `--all` picks these up for a fresh hunt;
- **no verified address** - every method ran and found nothing usable;
- **hunt incomplete** - some method has not run yet.

## Configuration

```json
"email_finder": {
  "search_provider": "duckduckgo",
  "searxng_url": "",
  "max_site_pages": 14,
  "max_search_pages": 4,
  "registry_sites": ["opencorporates.com"]
}
```

`search_provider` is `duckduckgo`, `searxng` (set `searxng_url` to an instance with the JSON API enabled) or `none`. Public search engines often block automated queries; that is reported as "not run", never as "no results".

## Salary from the listing

`findmejob search` also fills `salary_text` from the description when the source did not provide a salary field: the pay sentence is stored verbatim ("Salary: AED 18,000 - 20,000 per month"). It needs a money amount plus a pay word or a pay period, so company revenue, funding or "5 years" are not read as pay. A source-provided salary is never overwritten, and numbers are derived later by the existing salary parser without inventing a currency or period.
