# Job sources

Add sources in config.json under search.sources. All adapters read public
endpoints only; none of them logs in, scrapes behind auth, or bypasses
protections.

| type      | spec                                              | what it reads |
|-----------|---------------------------------------------------|---------------|
| greenhouse | {"type":"greenhouse","board":"<board>"}          | Public Greenhouse board API |
| lever     | {"type":"lever","company":"<company>"}            | Public Lever postings API |
| workable  | {"type":"workable","subdomain":"<sub>"}           | Public Workable widget API (shapes vary) |
| rss       | {"type":"rss","url":"...","name":"..."}           | Any RSS/Atom feed |
| remotive  | {"type":"remotive","search":"growth marketing"}   | Remotive free public API |
| jsonfile  | {"type":"jsonfile","path":"jobs.json"}            | Local list: saved searches, manual finds, demos |

Finding board tokens: a company jobs page on Greenhouse looks like
boards.greenhouse.io/<board>; on Lever, jobs.lever.co/<company>.

A failing source is reported in the run summary and skipped; it never stops
the other sources.

To add a source, see docs/extending-adapters.md.
