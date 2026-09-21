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

## Build a CV for any job ad

The CV builder works on demand, with or without a search run:

```bash
findmejob cv --job <id>            # tracked role (strong fits only)
findmejob cv --ad ad.txt --title "Growth Marketer" --company "Acme"
pbpaste | findmejob cv --ad -      # straight from the clipboard
findmejob cv --general             # one general profile CV, no targeting
```

Every run writes a Markdown source and a designed navy/gold PDF to
output/cvs/ (`--style classic` for the plain layout, `--photo me.jpg` to add
a photo, `--out <dir>` to redirect). It uses only master-CV facts and prints
a fidelity warning for anything that looks invented.

Or skip the keys entirely and run the offline demo: `scripts/demo.sh`.
