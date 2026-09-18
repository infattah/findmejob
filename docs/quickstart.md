# Quickstart

Requires Python 3.10+.

```bash
git clone https://github.com/infattah/findmejob.git
cd findmejob
pip install -e .            # adds the `findmejob` command
# optional: pip install -e .[browser] && playwright install chromium

findmejob init
```

1. Add your master CV. Any of these work:
   - Write it directly in the structured markdown format:
     `sample_data/master_cv.example.md` shows the shape.
   - Convert an existing CV: `findmejob ingest --cv my_cv.pdf` (needs
     `pdftotext`) or ask your coding agent to convert a DOCX/PDF into the
     markdown format, copying facts only.
2. Edit `config.json`: target role keywords, salary floor, locations,
   exclusions, sources. See docs/configuration.md.
3. Talk to it:

```bash
findmejob chat                # terminal chat
findmejob ui                  # http://127.0.0.1:8787 - same agent, same state
```

Try "find jobs", "status", "tailor <company>", "what's pending".

Or skip the keys entirely and run the offline demo: `scripts/demo.sh`.
