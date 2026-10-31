"""Fill the organisers' GEH pitch template with Lodestar content. Numbers come from the app/validation."""
import sys
from pptx import Presentation
from pptx.util import Inches

TPL, IMG, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
URL = "lodestar-utfz.onrender.com"

FILL = {
 0: [
  ("[Team name]", "Lodestar"),
  ("[Solution name]: [one sentence on what it does and for whom]",
   "Bankable demand forecasts that tell mini-grid developers and their lenders how much power a village will use, before anyone builds."),
  ("[#] [Brief title]", "03 · Predict mini-grid demand before building"),
  ("[Challenge track]", "2 · Digital Solutions & AI"),
  ("[Names and roles]", "Tushar Agarwal · product, data and engineering"),
 ],
 1: [
  ("[Who is affected, and what changes for them]", "Villages get mini-grids sized to real demand"),
  ("[Name the people in your brief who face this problem and how many there are]",
   "490 million people need the 217,000 mini-grids still to be built (ESMAP). Each is sized before a single customer exists, so developers guess demand: oversize and tariffs price villagers out; undersize and they get evening brownouts."),
  ("\"[A real quote or data point from the community]\"",
   "\"Survey-based estimates miss individual customers' demand by 65%.\" (CrossBoundary Innovation Lab)"),
  ("[Number]", "5 of 6"),
  ("[Your brief's impact metric, e.g., households reached]",
   "site-years of real metered demand inside our range, forecast from open data with no site meters (DR Congo)"),
  ("[From → To]", "+37% → +6%"),
  ("[Baseline today versus with your solution]",
   "year-3 oversizing at a metered site: desk estimate vs Lodestar plan (72% less mismatch)"),
  ("[Number]", "−49%"),
  ("[Second outcome, e.g., cost saved or hours of power]",
   "cost of power when sized on P50 instead of the optimistic case (avg. of 20 villages)"),
 ],
 2: [
  ("[What is new about your approach]", "A P90 for demand, borrowed from solar finance"),
  ("[How the problem is handled now, and why existing solutions fall short]",
   "Surveys or flat benchmarks give one day-one number: no range, no growth, never checked against meters. Lenders cannot price a guess."),
  ("[What you do differently, in one or two sentences]",
   "We forecast connections × consumption month by month with a calibrated P90/P50/P10 range, like a solar yield report, validated on real meters."),
  ("[Which root cause from your brief this solves]",
   "No defensible demand number before building, so sites are mis-sized or never financed."),
  ("[Step 1: what happens]", "Click any village: building footprints and OpenStreetMap give customers and anchors"),
  ("[Step 2: what happens]", "20,000 growth scenarios give P90/P50/P10 for 5 years, explained in plain words"),
  ("[Step 3: what happens]", "Size the system, stress-test the loan; shared meters sharpen it (Demand Bureau)"),
 ],
 3: [
  ("[How it stays affordable and pays for itself]", "Free to villages, pays for itself at scale"),
  ("[Cost / month]", "$0 / month"),
  ("[Compared with what they pay today, e.g., diesel, estimated bills]",
   "for households. Developers pay $300 per site report: 0.05% of a ~$585k mini-grid."),
  ("[Months or years]", "~200 reports/yr"),
  ("[Users, utility, government, investors: who pays what, and when]",
   "First: developers bidding into results-based financing, per report. Next: RBF programmes, $12k/yr screening. Later: lenders."),
  ("[Revenue, savings, or cost recovery that covers running costs without ongoing grants]",
   "Open data, 0.76 CPU-s per forecast. Break-even ~200 reports/yr: 3% of 6,116 planned sites (AMDA). No grant to run."),
  ("[Local maintenance, parts, and who is responsible after launch]",
   "Two analysts in Nairobi or Lagos; Python on a laptop, no API keys; quarterly re-fit on Bureau meter data."),
  ("[Diesel, emissions, or waste avoided per year]",
   "No stranded panels and batteries (desk plan oversized 61 kWp at one site, ours 9) and less backup diesel."),
 ],
 4: [
  ("[Proof it works, and how it grows]", "Live today, validated on real meters"),
  ("[Data you tested on and the result]", "DRC meters: demand in range 5 of 6 site-years"),
  ("[Standards, rules, or partners it fits]", "HOMER export; open licences; aggregate-only data"),
  ("[Top risk and how you will handle it]", "Risk: 3 metered sites → backtest operators first"),
  ("[Where, with whom, how many users]", "Nigeria: 10 sites with developers bidding into DARES"),
  ("[Next sites, utilities, or states]", "Score on meters; one RBF programme; Kenya next"),
  ("[Countries or networks; how unit cost falls]", "5 countries via the Bureau; ~1 CPU-s per site"),
  ("[What you need next: pilot partner, data, funding amount, or mentor]",
   "2–3 mini-grid operators to share historical meter data, and one RBF programme as pilot partner. Live: " + URL),
 ],
}

NOTES = {
 0: "Title (about 20 seconds). I'm Tushar, team Lodestar, Brief 03: predict mini-grid demand before building. Lodestar gives mini-grid developers and their lenders a demand forecast with a bankable range, from open data, before anyone builds. Each following slide answers one judging criterion.",
 1: "Impact (about 1 minute). 217,000 mini-grids are needed for 490 million people, and every one is sized on a guess: surveys miss individual demand by 65%. We forecast two real metered village mini-grids in DR Congo from open data only, without their meters: actual demand fell inside our P90-P10 range in 5 of 6 site-years. Replaying that real demand, a desk estimate would have oversized one site by 37%; our build-at-P50-then-expand plan by 6%. Right-sizing on P50 instead of the optimistic case cuts the cost of power by about half.",
 2: "Innovation (about 1 minute). Today a developer gets one day-one number. We borrow P50/P90 energy-yield reports from solar project finance and apply them to demand: connections times consumption, month by month, as a calibrated range. Two more ideas from other industries: a Demand Bureau where operators share meter aggregates like banks share credit data, and a public ledger that registers every forecast before the site is built, like weather-forecast verification.",
 3: "Sustainability (about 1 minute). Households never pay. Our first customers are developers bidding into results-based-financing programmes like Nigeria's DARES: their head is most on fire and they own the meters. They pay $300 per bankable report; financing programmes subscribe for portfolio screening; lenders follow once our track record builds. Running cost is near zero: open data, under a second of compute per forecast, so about 200 reports a year covers a two-person team. Environmentally, right-sizing avoids stranded panels and batteries, and backup diesel when systems are too small.",
 4: "Feasibility and scalability (about 1 minute), then close. It is live at lodestar-utfz.onrender.com with 20 villages in Nigeria, Kenya and DR Congo, a lender memo, a HOMER load export, SMS and USSD access, and a public track record. Honest risk: only three public metered sites exist, so the first step is backtesting operators' historical meters. Path: 10 pre-registered sites with developers bidding into DARES, then one RBF programme, then five countries. Our ask: 2-3 operators to share meter data and one RBF programme as pilot partner. Lodestar makes demand bankable, so the next 200,000 mini-grids get built at the right size.",
}


# The template's "Judges look for:" bar is guidance for teams; we use the same bar for our own takeaway.
BOTTOM_LINE = {
 1: "On real meters, demand landed inside our range in 5 of 6 site-years, and right-sizing roughly halves the cost of power.",
 2: "A calibrated range, a growth curve and a lender view, validated on meters: none of the open tools we found do all four.",
 3: "Free for villagers, under a second of compute per forecast, and self-funding at about 200 paid reports a year.",
 4: "Live today on real data; the next step is a 10-site pilot with developers bidding into Nigeria's DARES programme.",
}


def set_par(par, text):
    runs = par.runs
    runs[0].text = text
    for r in runs[1:]:
        r.text = ""


def all_text_shapes(shapes):
    for s in shapes:
        if s.shape_type == 6:
            yield from all_text_shapes(s.shapes)
        elif s.has_text_frame:
            yield s


prs = Presentation(TPL)
for idx, pairs in FILL.items():
    slide = prs.slides[idx]
    queue = list(pairs)
    for shp in all_text_shapes(slide.shapes):
        for par in shp.text_frame.paragraphs:
            t = "".join(r.text for r in par.runs).strip()
            for k, (old, new) in enumerate(queue):
                if t == old:
                    set_par(par, new)
                    queue.pop(k)
                    break
    if queue:
        raise SystemExit(f"slide {idx + 1}: unmatched {queue}")
    if idx in BOTTOM_LINE:
        bar = next(s for s in slide.shapes if s.name == "Judges look for text")
        runs = bar.text_frame.paragraphs[0].runs
        runs[0].text = "Bottom line:"
        runs[1].text = "  " + BOTTOM_LINE[idx]
        for r in runs[2:]:
            r.text = ""
        bar.name = "Bottom line text"
    slide.notes_slide.notes_text_frame.text = NOTES[idx]

# slide 5: replace the image placeholder with the app screenshot (forecast vs real meters)
s5 = prs.slides[4]
box = next(s for s in s5.shapes if s.name == "Prototype image placeholder")
for s in list(s5.shapes):
    if s.name in ("Placeholder icon",) or (s.has_text_frame and s.text_frame.text.startswith("[Screenshot")):
        s._element.getparent().remove(s._element)
x, y, w, h = box.left, box.top, box.width, box.height
box._element.getparent().remove(box._element)
pic = s5.shapes.add_picture(IMG, x, y, width=w)
if pic.height > h:
    ratio = h / pic.height
    pic.width, pic.height = int(pic.width * ratio), h
pic.name = "Prototype screenshot"
pic._element.nvPicPr.cNvPr.set("descr", "Lodestar app: Mutwanga year-3 forecast with P90-P10 band and the real metered demand line")
prs.save(OUT)
print("saved", OUT)
