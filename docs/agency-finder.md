# Agency finder

Recruitment agencies place people in roles that are never advertised. `findmejob agencies` finds them for any country, city and industry, checks that each one is a real business that can receive your CV, and keeps them in the tracker.

It has no built-in list of agencies and no region-specific sources. Everything it searches comes from generic methods plus your own configuration.

## The rules

- **Every method reports what happened.** Each discovery method ends as `found`, `empty`, `not_run` or `error`, with a reason. A method that could not run - no search provider, no API key, blocked by a bot check, skipped by you - is shown as `not_run` or `error`, never as "no agencies found".
- **Every fact has a source.** Name, website, address, phone, rating, listed email, LinkedIn page, verified contact: each one keeps the URL or record it was read from and the method that read it (`findmejob agencies --list --evidence`).
- **Nothing is guessed.** No invented domains and no pattern-built addresses. Contact addresses come from the [email finder](email-finder.md), with the same rules.
- **Conclusions need checks that ran.** `validated` and `no_verified_contact` are only set from checks that actually ran. Anything else stays `discovered` and lists the checks still missing.

## Discovery methods

| Method | What it does | Needs |
| --- | --- | --- |
| `web_search` | Searches agency terms + industry + place and keeps results that look like agencies on their own website. | a search provider |
| `maps` | Google Places Text Search for the same terms. Adds address, phone, rating and review count. | a Google Places API key in the variable named by `maps_api_key_env` |
| `openstreetmap` | OpenStreetMap objects tagged `office=employment_agency` in the country (Overpass API). City filter uses OSM address tags. | a country name or ISO code |
| `directories` | Finds "list of agencies" and directory pages by search (plus any `directory_sites` you add) and reads agency links off them. | a search provider |
| `job_boards` | Employer listings on the job boards you configure in `job_board_sites`. | a search provider and at least one site |
| `tracker` | Employers in roles you already track, in that place, that are agencies or say they recruit "on behalf of our client". | tracked roles |
| `supplied` | Pages or candidates you or your agent opened: `[{"url", "text"}]` or `[{"name", "website", "source_url"}]`. | `--pages file.json` |

Choose methods with `--methods web_search,openstreetmap` or drop some with `--skip maps`. Skipped methods are listed as skipped.

The same agency found by several methods is merged into one record: by website domain first, then by its distinctive name words.

## Validation checks

| Check | Pass means |
| --- | --- |
| `website` | The official site resolves and its homepage names the agency. A bot block (HTTP 401/403/429/503) or timeout is an `error`, not a failure. |
| `mx` | The domain has a live MX record, so it can receive mail. |
| `contact_email` | The email finder found a verified address on the agency's own site. Only runs as a conclusion when the site names the agency; otherwise leads are kept and none are verified. |
| `linkedin` | The official site links a LinkedIn company page, or a LinkedIn company result matches the name. |
| `maps_presence` | Listed on Google Maps or OpenStreetMap. |
| `reviews` | A public rating and review count, where accessible (Google Places). |

LinkedIn, maps and reviews are legitimacy signals. They are shown on each agency but do not decide the status on their own.

## Statuses

| Status | Meaning |
| --- | --- |
| `discovered` | Found; one or more deciding checks have not run yet (see the listed missing checks). |
| `validated` | Website resolves and names the agency, live MX, and a verified contact address. |
| `contacted` | You sent your CV. Needs a validated agency and proof (the sent-message id or link). |
| `no_verified_contact` | A deciding check ran and failed: the website does not resolve, the domain has no MX, or every email-finder method ran without a verified address. |

## Using it

```bash
findmejob agencies --country "New Zealand" --industry nursing
findmejob agencies --country Kenya --city Nairobi --methods web_search,openstreetmap,tracker
findmejob agencies --country XX --country-code XX --skip maps     # pass an ISO code if the name is not recognised
findmejob agencies --country Chile --pages opened.json --no-validate
findmejob agencies --revalidate --status discovered
findmejob agencies --list --status validated --evidence
findmejob agencies --agency <id or name> --outcome contacted --proof <sent-message id or link>
```

## Configuration

`config.json` → `agency_finder`:

- `methods` - default method list (empty = all).
- `search_terms` - the agency phrases searched (add other languages here).
- `agency_keywords` - words that mark a business as an agency (default list covers common English terms).
- `directory_sites`, `job_board_sites` - sites that matter where you are looking.
- `aggregator_hosts` - extra hosts that are never an agency's own website.
- `maps_api_key_env` - name of the environment variable that holds your Google Places key (default `GOOGLE_MAPS_API_KEY`, set it in `.env`).
- `overpass_url` - Overpass API instance. The public servers are often busy; a timeout is reported as `error`.
- `search_provider` / `searxng_url` - optional; defaults to the `email_finder` provider.

## Limits

- Free HTML search endpoints often answer automated queries with a bot check. The search-based methods then report `error`. A SearXNG instance, a Places API key, OpenStreetMap, your tracker and `--pages` still work.
- OpenStreetMap coverage of agencies varies a lot by country.
- Reviews need a Places API key or pages you supply.
- The tool never sends anything. `contacted` is a record of what you did, with proof.
