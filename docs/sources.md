# Job sources

Add sources in config.json under search.sources. All built-in adapters read
public, zero-auth endpoints only; none of them logs in, scrapes behind
authentication, or bypasses protections.

| type      | spec                                              | what it reads |
|-----------|---------------------------------------------------|---------------|
| greenhouse | {"type":"greenhouse","board":"<board>"}          | Public Greenhouse board API |
| lever     | {"type":"lever","company":"<company>"}            | Public Lever postings API |
| ashby     | {"type":"ashby","board":"<board>"}                | Public Ashby posting API (incl. compensation when published) |
| smartrecruiters | {"type":"smartrecruiters","company":"<co>"} | Public SmartRecruiters postings API |
| workable  | {"type":"workable","subdomain":"<sub>"}           | Public Workable widget API (shapes vary) |
| rss       | {"type":"rss","url":"...","name":"..."}           | Any RSS/Atom feed |
| remotive  | {"type":"remotive","search":"growth marketing"}   | Remotive free public API |
| jsonfile  | {"type":"jsonfile","path":"jobs.json"}            | Local list: saved searches, manual finds, agent-provided leads, demos |

Finding board tokens: a company jobs page on Greenhouse looks like
boards.greenhouse.io/<board>; on Lever, jobs.lever.co/<company>; on Ashby,
jobs.ashbyhq.com/<board>.

A failing source is reported in the run summary and skipped; it never stops
the other sources.

## Caching and change detection

Repeated runs go through an on-disk HTTP cache (`paths.cache`, default
`data/http-cache`). Fresh entries inside `search.cache_ttl_seconds`
(default 3600; 0 disables) are served from disk, and stale entries are
revalidated with ETag / Last-Modified, so a source that has not changed
costs one conditional request and no re-processing. If a source errors but
a cached body exists, the run degrades to the stale copy instead of failing.

## Deduplication

The same role often appears on an ATS, an aggregator and the company
careers page. Search runs deduplicate on the canonical URL (tracking
parameters stripped) and on a normalized company/title/location signature -
within the batch and against everything already tracked. Duplicates are
merged, never dropped: the kept record stores every alternate source and
URL (`findmejob list` plus the tracker's job links), and a `duplicate`
event records where else the role was seen.

## Liveness

A fetched listing is a lead, not proof the role is open. Run
`findmejob refresh --verify` to re-check tracked listings: clear 404/410
responses and explicit "no longer available" pages are marked expired
(status skipped with the reason); anything ambiguous stays untouched.

## Bringing your own sources

**Indeed MCP (agent-driven).** When you drive findmejob through a tool-capable
agent that has an Indeed MCP connection, let the agent search Indeed and write
the results as JSON (the sample_data/sample_jobs.json shape), then ingest them
with a `jsonfile` source. This keeps Indeed's official interface between you
and Indeed, and keeps the core free of Indeed-specific code.

**JobSpy (optional, off by default).** [JobSpy](https://github.com/speedyapply/JobSpy)
can collect from boards that have no public API (Indeed, LinkedIn, Glassdoor,
Google Jobs, ZipRecruiter, Bayt, Naukri...). It is a scraping library, so:

- it is **not** a dependency of findmejob and is never installed by default;
- run it yourself, in its own environment, and export results to the
  `jsonfile` shape - the same ingestion path as Indeed MCP;
- do not point it at sites behind your logged-in session (LinkedIn
  prohibits unauthorized scraping and may restrict your account), do not
  use proxy rotation to evade blocks, and expect rate limits;
- treat every JobSpy result as a lead: verify liveness (`refresh --verify`)
  and legitimacy (docs/company-verification.md) before applying;
- keep JobSpy's raw salary text - its period/currency guesses are known to
  be wrong, and findmejob's salary module will normalize honestly from the
  raw text.

To add a first-party source, see docs/extending-adapters.md.
